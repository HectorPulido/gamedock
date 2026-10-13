"""Host-side companion for QA_AUDIO_TEST=1 in selkies_browser.py.

Run both commands against the SAME disposable QA deployment:
  # Browser container: QA_AUDIO_TEST=1 QA_ARTIFACTS=/artifacts python tests/selkies_browser.py
  # Docker host, with browser's /artifacts bind-mounted at ./artifacts:
  python3 tests/selkies_audio_tone.py --artifacts ./artifacts

Delete stale artifacts/audio-ready.json BEFORE starting the browser test. This
helper waits for the new SID marker, generates a known 440 Hz PCM WAV inside
that QA game's container, and injects it into its PulseAudio output sink.
The browser's AnalyserNode verifies nonzero decoded RMS and writes
selkies-audio-proof.json. No Docker socket is mounted into game containers.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifacts',type=Path,required=True)
args=parser.parse_args()
marker=args.artifacts/'audio-ready.json'
deadline=time.monotonic()+45
while not marker.exists():
    if time.monotonic()>deadline:raise TimeoutError('Browser audio-ready marker not received')
    time.sleep(.2)
sid=json.loads(marker.read_text())['sid']
if not re.fullmatch(r'[a-f0-9]{32}',sid):raise ValueError('Invalid QA session marker')
names=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
matching=[name for name in names if name.endswith(sid)]
if len(matching)!=1:raise ValueError('QA session container not found uniquely')
container=matching[0]
script='''import math,struct,wave
w=wave.open('/tmp/qa-tone.wav','wb')
w.setparams((1,2,48000,0,'NONE','not compressed'))
w.writeframes(b''.join(struct.pack('<h',int(10000*math.sin(2*math.pi*440*i/48000))) for i in range(48000*8)))
w.close()
'''
subprocess.run(['docker','exec','-i',container,'python3','-'],input=script,text=True,check=True)
subprocess.run(['docker','exec','-e','PULSE_SERVER=unix:/tmp/gamedock-runtime/pulse/native',container,'paplay','--device=output','/tmp/qa-tone.wav'],check=True)
print('Injected QA tone for session',sid)
