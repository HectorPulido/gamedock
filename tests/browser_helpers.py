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
            if frame and frame.locator("canvas").count():
                frame.wait_for_function(
                    """minimum => [...document.querySelectorAll('canvas')].some(c => {
                  if(c.width < 640 || c.height < 480) return false;
                  const ctx=c.getContext('2d'); if(!ctx) return false;
                  const data=ctx.getImageData(0,0,c.width,c.height).data; const colors=new Set();
                  for(let i=0;i<data.length;i+=160) if(data[i+3]) colors.add(data.slice(i,i+4).join(','));
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
