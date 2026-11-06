"""Share native stop intent before the Tk thread has observed runner readiness."""
import threading


class NativeRunSlot:
    def __init__(self, events, cancel):
        self.events = events
        self.cancel = cancel
        self.lock = threading.Lock()
        self.runner = None

    def run(self, runner):
        try:
            with self.lock:
                self.runner = runner
                if self.cancel.is_set():
                    runner.stop()
            self.events.put(dict(type='runner_ready', runner=runner))
            return runner.run()
        finally:
            with self.lock:
                self.runner = None

    def stop(self):
        with self.lock:
            self.cancel.set()
            if self.runner is not None:
                self.runner.stop()
