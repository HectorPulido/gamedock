"""Shared helpers for the disposable QA browser suite."""

import os
from pathlib import Path
import time
from playwright.sync_api import expect

URL = os.getenv("QA_URL", "http://localhost:18088")
ARTIFACTS = Path(os.getenv("QA_ARTIFACTS", "/artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
ENV = Path(os.getenv("QA_ENV_FILE", "/qa.env"))
PASSWORD = next(
    line.split("=", 1)[1]
    for line in ENV.read_text().splitlines()
    if line.startswith("ADMIN_PASSWORD=")
)


def admin_token(request):
    response = request.post(
        URL + "/api/auth/login", data={"username": "admin", "password": PASSWORD}
    )
    assert response.ok, response.text()
    return response.json()["token"]


def invitation(request, token):
    response = request.post(
        URL + "/api/admin/invitations",
        data={},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status == 201, response.text()
    return response.json()["code"]


def rendered(page, colors=3):
    expect(page.locator("#desktop-frame")).to_be_visible()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        frame = page.locator("#desktop-frame").element_handle().content_frame()
        try:
            if frame and frame.locator("canvas,video").count():
                frame.wait_for_function(
                    """minimum => [...document.querySelectorAll('canvas:not(.fsr-overlay),video')].some(source => {
                  const w=source.videoWidth || source.width, h=source.videoHeight || source.height;
                  if(w < 320 || h < 240 || source.getBoundingClientRect().width <= 0) return false;
                  // Reading through a scratch canvas works for WebGL, transferred
                  // canvases and video sinks without changing their context type.
                  const probe=document.createElement('canvas'); probe.width=160;probe.height=90;
                  const ctx=probe.getContext('2d'); if(!ctx) return false;
                  try {ctx.drawImage(source,0,0,160,90);} catch {return false;}
                  const data=ctx.getImageData(0,0,160,90).data; const colors=new Set();
                  for(let i=0;i<data.length;i+=16) if(data[i+3]) colors.add(data.slice(i,i+4).join(','));
                  return colors.size>minimum;
                })""",
                    arg=colors,
                    timeout=3000,
                )
                return frame
        except Exception:
            pass
        page.wait_for_timeout(300)
    raise AssertionError("Desktop did not render game pixels")


def centered(page):
    stage = page.locator("#desktop-stage").bounding_box()
    frame = page.locator("#desktop-frame").bounding_box()
    assert abs(frame["x"] + frame["width"] / 2 - stage["x"] - stage["width"] / 2) < 2
    assert abs(frame["y"] + frame["height"] / 2 - stage["y"] - stage["height"] / 2) < 2
    assert (
        frame["width"] <= stage["width"] + 1 and frame["height"] <= stage["height"] + 1
    )
