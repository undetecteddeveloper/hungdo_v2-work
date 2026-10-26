"""Scene base class and a stack-based SceneManager with deferred transitions."""
import logging

from . import config

log = logging.getLogger(config.LOGGER_NAME)


class Scene:
    is_overlay = False            # True -> scene below is drawn (not updated) first

    def __init__(self, app):
        self.app = app

    def on_enter(self, **kwargs):
        """Called each time the scene becomes active via switch/push."""

    def on_exit(self):
        """Called when the scene is removed from the stack."""

    def on_resume(self):
        """Called when the scene becomes top again after the overlay above it was popped."""

    def handle_event(self, event):
        """Mouse events already carry LOGICAL pos (or were dropped if outside)."""

    def on_resize(self, old_w: int):
        """The canvas width changed (config.LOGICAL_W): rebuild width-dependent layout/backgrounds."""

    def update(self, dt):
        """Fixed timestep (config.PHYSICS_DT)."""

    def draw(self, surf):
        pass


class SceneManager:
    """Owns the scene stack. switch/push/pop are queued and applied by App between steps."""

    MAX_CHAIN = 16                # guard against scenes switching each other forever

    def __init__(self, app):
        self.app = app
        self._factories = {}
        self._instances = {}
        self._stack = []          # list of (name, scene)
        self._pending = []        # list of (op, name, kwargs)

    #Registry
    def register(self, name: str, factory) -> None:
        """factory(app) -> Scene; created lazily on first use, then cached."""
        self._factories[name] = factory
        self._instances.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._factories

    @property
    def names(self) -> list:
        return list(self._factories)

    def get(self, name: str) -> Scene:
        """Cached scene instance (created on demand)."""
        scene = self._instances.get(name)
        if scene is None:
            if name not in self._factories:
                raise KeyError(f"Unknown scene '{name}'")
            scene = self._factories[name](self.app)
            self._instances[name] = scene
        return scene

    #Requests (deferred)
    def switch(self, name: str, **kw) -> None:
        """Replace the whole stack with scene `name`."""
        self._pending.append(("switch", name, kw))

    def push(self, name: str, **kw) -> None:
        self._pending.append(("push", name, kw))

    def pop(self) -> None:
        self._pending.append(("pop", None, None))

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    #Stack queries
    @property
    def top(self):
        return self._stack[-1][1] if self._stack else None

    @property
    def top_name(self):
        return self._stack[-1][0] if self._stack else None

    @property
    def stack_names(self) -> list:
        return [n for n, _ in self._stack]

    def visible(self) -> list:
        """Scenes to draw, bottom to top: from the highest non-overlay scene upwards."""
        start = 0
        for i in range(len(self._stack) - 1, -1, -1):
            if not self._stack[i][1].is_overlay:
                start = i
                break
        return [s for _, s in self._stack[start:]]

    #Applying
    def apply_pending(self) -> bool:
        """Apply queued transitions; returns True if the stack changed."""
        changed = False
        rounds = 0
        while self._pending:
            rounds += 1
            if rounds > self.MAX_CHAIN:
                log.error("Scene transition loop detected; dropping %d requests", len(self._pending))
                self._pending.clear()
                break
            ops, self._pending = self._pending, []
            for op, name, kw in ops:
                if op == "switch":
                    self._do_switch(name, kw)
                elif op == "push":
                    self._do_push(name, kw)
                else:
                    self._do_pop()
                changed = True
        return changed

    def _do_switch(self, name, kw):
        if name not in self._factories:
            log.error("switch: unknown scene '%s'", name)
            return
        while self._stack:
            _, scene = self._stack.pop()
            scene.on_exit()
        scene = self.get(name)
        self._stack.append((name, scene))
        scene.on_enter(**kw)

    def _do_push(self, name, kw):
        if name not in self._factories:
            log.error("push: unknown scene '%s'", name)
            return
        # A scene instance can only be on the stack once: unwind down to it
        if name in self.stack_names:
            while self._stack and self._stack[-1][0] != name:
                _, scene = self._stack.pop()
                scene.on_exit()
            _, scene = self._stack.pop()
            scene.on_exit()
        scene = self.get(name)
        self._stack.append((name, scene))
        scene.on_enter(**kw)

    def _do_pop(self):
        if not self._stack:
            return
        _, scene = self._stack.pop()
        scene.on_exit()
        if self._stack:
            self._stack[-1][1].on_resume()
        else:
            log.warning("Scene stack is empty after pop")

    def relayout(self, old_w: int) -> None:
        """Tell every created scene (stacked or cached) that the canvas width changed."""
        for name, scene in list(self._instances.items()):
            try:
                scene.on_resize(old_w)
            except Exception:
                log.exception("Scene '%s' failed to relayout", name)

    #Frame helpers (used by App)
    def handle_event(self, event) -> None:
        top = self.top
        if top is not None:
            top.handle_event(event)

    def update(self, dt) -> None:
        top = self.top
        if top is not None:
            top.update(dt)

    def draw(self, surf) -> None:
        for scene in self.visible():
            scene.draw(surf)
