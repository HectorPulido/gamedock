/* Client-only AMD FSR1: upstream EASU then RCAS, after the stream decodes.
 * The overlay never receives input; the original iframe maps all coordinates.
 */
window.GameDockFSR = (() => {
  const vertex = `#version 300 es
  void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}`;
  const prefix = `#version 300 es
precision highp float;
precision highp int;
#define A_GPU 1
#define A_GLSL 1
#define A_SKIP_EXT 1
`;
  function shaderSource(pass) {
    const header = window.GameDockFSRHeaders;
    // ES 3.00 lacks the unused upstream bitfield intrinsics and requires
    // explicit unsigned literals. The EASU/RCAS arithmetic is unchanged.
    const a = header.a
      .replace(
        "bitfieldExtract(src,ASU1(off),ASU1(bits))",
        "(src >> off) & (0xffffffffu >> (32u-bits))",
      )
      .replace(
        "bitfieldInsert(src,ins,0,ASU1(bits))",
        "(src & ~(0xffffffffu >> (32u-bits))) | (ins & (0xffffffffu >> (32u-bits)))",
      );
    const fsr = header.fsr
      .replace("con3[2]=con3[3]=0;", "con3[2]=con3[3]=0u;")
      .replace("con[2]=0;", "con[2]=0u;")
      .replace("con[3]=0;", "con[3]=0u;");
    const common = prefix + `#define FSR_${pass}_F 1\n` + a + "\n" + fsr;
    if (pass === "EASU")
      return (
        common +
        `
uniform sampler2D image; uniform vec2 inputSize; uniform vec2 outputSize;
out vec4 color;
// ES 3.00 has no textureGather. Preserve GLSL gather order exactly.
vec4 gatherChannel(vec2 p,int c){ivec2 q=ivec2(floor(p*inputSize-.5));ivec2 hi=ivec2(inputSize)-1;
return vec4(texelFetch(image,clamp(q+ivec2(0,1),ivec2(0),hi),0)[c],texelFetch(image,clamp(q+ivec2(1,1),ivec2(0),hi),0)[c],texelFetch(image,clamp(q+ivec2(1,0),ivec2(0),hi),0)[c],texelFetch(image,clamp(q,ivec2(0),hi),0)[c]);}
vec4 FsrEasuRF(vec2 p){return gatherChannel(p,0);} vec4 FsrEasuGF(vec2 p){return gatherChannel(p,1);} vec4 FsrEasuBF(vec2 p){return gatherChannel(p,2);}
void main(){uvec4 a,b,c,d;FsrEasuCon(a,b,c,d,inputSize.x,inputSize.y,inputSize.x,inputSize.y,outputSize.x,outputSize.y);vec3 rgb;FsrEasuF(rgb,uvec2(gl_FragCoord.xy),a,b,c,d);color=vec4(rgb,1.);}`
      );
    return (
      common +
      `
uniform sampler2D image;uniform vec2 outputSize;uniform float sharpness;out vec4 color;
vec4 FsrRcasLoadF(ivec2 p){return texelFetch(image,clamp(p,ivec2(0),ivec2(outputSize)-1),0);}
void FsrRcasInputF(inout float r,inout float g,inout float b){}
void main(){uvec4 con;FsrRcasCon(con,sharpness);vec3 rgb;FsrRcasF(rgb.r,rgb.g,rgb.b,uvec2(gl_FragCoord.xy),con);color=vec4(rgb,1.);}`
    );
  }
  function create(frame) {
    const canvas = document.createElement("canvas");
    canvas.className = "fsr-overlay";
    Object.assign(canvas.style, {
      position: "absolute",
      pointerEvents: "none",
      zIndex: "1",
      imageRendering: "auto",
    });
    canvas.setAttribute("aria-hidden", "true");
    let gl,
      programs,
      input,
      intermediate,
      fbo,
      active = false,
      failed = false,
      dirty = true,
      raf = 0,
      lastRect = "",
      source;
    const stats = {
      mode: "smooth",
      reason: "",
      frames: 0,
      submit_ms: 0,
      source: "",
      output: "",
    };
    function compile(type, code) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, code);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        const error = gl.getShaderInfoLog(shader);
        gl.deleteShader(shader);
        throw Error(error);
      }
      return shader;
    }
    function program(pass) {
      const p = gl.createProgram(),
        v = compile(gl.VERTEX_SHADER, vertex),
        f = compile(gl.FRAGMENT_SHADER, shaderSource(pass));
      gl.attachShader(p, v);
      gl.attachShader(p, f);
      gl.linkProgram(p);
      gl.deleteShader(v);
      gl.deleteShader(f);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS))
        throw Error(gl.getProgramInfoLog(p));
      return p;
    }
    function texture() {
      const t = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, t);
      for (const key of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER])
        gl.texParameteri(gl.TEXTURE_2D, key, gl.NEAREST);
      for (const key of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T])
        gl.texParameteri(gl.TEXTURE_2D, key, gl.CLAMP_TO_EDGE);
      return t;
    }
    function fallback(reason) {
      failed = true;
      active = false;
      canvas.remove();
      stats.mode = "smooth";
      stats.reason = reason;
      frame.dispatchEvent(
        new CustomEvent("fsr-status", { detail: { ...stats } }),
      );
    }
    function start() {
      if (gl || failed) return;
      try {
        gl = canvas.getContext("webgl2", {
          alpha: false,
          antialias: false,
          depth: false,
          stencil: false,
          preserveDrawingBuffer: false,
        });
        if (!gl) throw Error("WebGL 2 is unavailable");
        programs = [program("EASU"), program("RCAS")];
        input = texture();
        intermediate = texture();
        fbo = gl.createFramebuffer();
        canvas.addEventListener("webglcontextlost", (event) => {
          event.preventDefault();
          fallback("Graphics context lost; using Smooth");
        });
      } catch (error) {
        fallback("FSR unavailable; using Smooth");
        console.warn("GameDock FSR:", error.message);
      }
    }
    function render() {
      raf = 0;
      if (!active || failed) return;
      try {
        const doc = frame.contentDocument;
        source = [...(doc?.querySelectorAll("canvas:not(.fsr-overlay),video") || [])]
          .filter(
            (c) => (c.videoWidth || c.width) && (c.videoHeight || c.height) && c.getBoundingClientRect().width > 0,
          )
          .sort((a, b) => (b.videoWidth || b.width) * (b.videoHeight || b.height) - (a.videoWidth || a.width) * (a.videoHeight || a.height))[0];
        if (!source || doc.hidden || document.hidden) {
          canvas.hidden = true;
          dirty = true;
          raf = requestAnimationFrame(render);
          return;
        }
        const sourceWidth = source.videoWidth || source.width;
        const sourceHeight = source.videoHeight || source.height;
        const r = source.getBoundingClientRect(),
          fr = frame.getBoundingClientRect();
        const sx = fr.width / frame.offsetWidth,
          sy = fr.height / frame.offsetHeight;
        const w = Math.round(r.width * sx * devicePixelRatio),
          h = Math.round(r.height * sy * devicePixelRatio);
        // Keep the existing renderer for native-size/downscaled content.
        if (w <= sourceWidth && h <= sourceHeight) {
          canvas.hidden = true;
          dirty = true;
          stats.mode = "smooth (no enlargement)";
          raf = requestAnimationFrame(render);
          return;
        }
        const rect = [
          r.left,
          r.top,
          r.width,
          r.height,
          fr.left,
          fr.top,
          w,
          h,
        ].join(",");
        if (rect !== lastRect) {
          dirty = true;
          lastRect = rect;
          Object.assign(canvas.style, {
            left: source.offsetLeft + "px",
            top: source.offsetTop + "px",
            width: r.width + "px",
            height: r.height + "px",
          });
        }
        if (dirty) {
          const began = performance.now();
          start();
          if (failed) return;
          const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
          if (w > max || h > max || sourceWidth > max || sourceHeight > max)
            throw Error("Canvas exceeds GPU texture limit");
          if (canvas.parentElement !== source.parentElement)
            source.parentElement.append(canvas);
          canvas.hidden = false;
          if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
            gl.bindTexture(gl.TEXTURE_2D, intermediate);
            gl.texImage2D(
              gl.TEXTURE_2D,
              0,
              gl.RGBA,
              w,
              h,
              0,
              gl.RGBA,
              gl.UNSIGNED_BYTE,
              null,
            );
          }
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, input);
          // Flip DOM top-first rows into GL bottom-first coordinates once on upload.
          gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.RGBA,
            gl.RGBA,
            gl.UNSIGNED_BYTE,
            source,
          );
          gl.viewport(0, 0, w, h);
          gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
          gl.framebufferTexture2D(
            gl.FRAMEBUFFER,
            gl.COLOR_ATTACHMENT0,
            gl.TEXTURE_2D,
            intermediate,
            0,
          );
          if (
            gl.checkFramebufferStatus(gl.FRAMEBUFFER) !==
            gl.FRAMEBUFFER_COMPLETE
          )
            throw Error("Incomplete FSR framebuffer");
          gl.useProgram(programs[0]);
          gl.uniform1i(gl.getUniformLocation(programs[0], "image"), 0);
          gl.uniform2f(
            gl.getUniformLocation(programs[0], "inputSize"),
            sourceWidth,
            sourceHeight,
          );
          gl.uniform2f(gl.getUniformLocation(programs[0], "outputSize"), w, h);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          gl.bindTexture(gl.TEXTURE_2D, intermediate);
          gl.useProgram(programs[1]);
          gl.uniform1i(gl.getUniformLocation(programs[1], "image"), 0);
          gl.uniform2f(gl.getUniformLocation(programs[1], "outputSize"), w, h);
          gl.uniform1f(gl.getUniformLocation(programs[1], "sharpness"), 0.5);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
          if (gl.getError() !== gl.NO_ERROR) throw Error("FSR render failed");
          stats.mode = "fsr";
          stats.frames++;
          stats.submit_ms = performance.now() - began;
          stats.source = sourceWidth + "×" + sourceHeight;
          stats.output = w + "×" + h;
          dirty = false;
        }
      } catch (error) {
        fallback(error.message);
        return;
      }
      raf = requestAnimationFrame(render);
    }
    function enable(value) {
      if (active === value) return;
      active = value;
      dirty = true;
      if (value && !failed) {
        stats.mode = "fsr";
        raf = requestAnimationFrame(render);
      } else {
        cancelAnimationFrame(raf);
        canvas.remove();
        stats.mode = "smooth";
      }
    }
    function dispose() {
      enable(false);
      if (gl) {
        for (const p of programs || []) gl.deleteProgram(p);
        if (input) gl.deleteTexture(input);
        if (intermediate) gl.deleteTexture(intermediate);
        if (fbo) gl.deleteFramebuffer(fbo);
        gl = null;
      }
      canvas.width = 0;
      canvas.height = 0;
      lastRect = "";
      failed = false;
      stats.reason = "";
    }
    return {
      enable,
      dispose,
      dirty() {
        dirty = true;
      },
      sample() {
        return { ...stats };
      },
    };
  }
  return { create };
})();
