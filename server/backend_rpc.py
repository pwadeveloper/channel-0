import json
import os
import sys
import threading
import time

from tv import HisenseTV, _cached_host

RETRY_AFTER = 5.0
LEGACY_APP_NAME = os.environ.get("LAUNCHER_APP_NAME", "Launcher")

_lock = threading.Lock()
_tv = {"conn": None, "next_try": 0.0}


def _get():
    """Return a connected HisenseTV, (re)connecting and rediscovering as needed."""
    conn = _tv["conn"]
    if conn is not None:
        return conn
    if time.time() < _tv["next_try"]:
        raise ConnectionError("TV offline")
    try:
        conn = HisenseTV()
        conn.connect()
    except Exception:
        _tv["next_try"] = time.time() + RETRY_AFTER
        raise
    _tv["conn"] = conn
    return conn


def _drop():
    conn = _tv["conn"]
    _tv["conn"] = None
    if conn is not None:
        try:
            conn.disconnect()
        except Exception:
            pass


def _close_front(tv):
    """Older firmware's home screen is an overlay, and relaunching an app already behind it doesn't dismiss it.
    Exit closes both, so the next launch starts the launcher fresh in front."""
    if tv.legacy:
        tv.send_key("KEY_EXIT")
        time.sleep(1.5)


def handle(cmd, arg):
    with _lock:
        try:
            tv = _get()
        except Exception as e:
            _drop()
            return {"ok": False, "offline": True, "error": str(e), "host": _cached_host()}

        try:
            if cmd == "ping":
                return {"ok": True, "host": tv.host}
            if cmd == "state":
                return {"ok": True, "data": tv.get_state()}
            if cmd == "volume":
                return {"ok": True, "data": tv.get_volume()}
            if cmd == "set_volume":
                tv.set_volume(int(arg))
                return {"ok": True}
            if cmd == "key":
                tv.send_key(str(arg))
                return {"ok": True}
            if cmd in ("launch", "launch_fresh"):
                try:
                    if cmd == "launch_fresh":
                        if tv.find_app(str(arg)) is None:   # check before closing what's on screen
                            raise LookupError(f"app not installed: {arg}")
                        _close_front(tv)
                    app = tv.launch_app(str(arg))
                except LookupError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True, "data": app}
            if cmd == "open_url":
                # VIDAA web apps are just a name + URL, so any page can be opened.
                # Older firmware sends storeType 99 to the app store; it opens web apps as urlType 37 / storeType 0.
                # It also keeps one instance per name, so a name that once failed to load stays on its error page.
                # Once installed ("Install to app screen") it stores "http://host:port/" as "http:host:port";
                # any other spelling counts as a new app and brings the install prompt back.
                url = str(arg).replace("://", ":", 1).rstrip("/") if tv.legacy else str(arg)
                app = ({"appId": "", "name": LEGACY_APP_NAME, "url": url, "urlType": 37, "storeType": 0}
                       if tv.legacy else
                       {"appId": "9001", "name": "HisenseBar", "url": str(arg), "storeType": 99})
                _close_front(tv)
                tv._call("ui_service", "launchapp", app)
                return {"ok": True}
            if cmd == "apps":
                return {"ok": True, "data": tv.app_list()}
            if cmd == "source":
                tv.change_source(arg)
                return {"ok": True}
            if cmd == "sources":
                return {"ok": True, "data": tv.source_list()}
            return {"ok": False, "error": f"unknown cmd {cmd!r}"}
        except Exception as e:
            _drop()
            return {"ok": False, "offline": True, "error": str(e)}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle(req.get("cmd"), req.get("arg"))
        resp["id"] = req.get("id")
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
