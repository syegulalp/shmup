from __future__ import annotations

import pyglet
pyglet.options.debug_gl=False
pyglet.options.vsync=False

import weakref

from math import radians, degrees, floor, ceil, sin, cos

from pyglet.gl import glEnable, glDisable, GL_DEPTH_TEST, GL_CULL_FACE, Config
from pyglet.math import Vec2, Vec3, Mat4, clamp
from pyglet.window import key as _key

from time import perf_counter
from itertools import product

from pyglet import resource
import os
cwd = f"{os.getcwd()}/data"
resource.path=[f"{cwd}/audio", f"{cwd}/fonts"]
resource.reindex()

resource.add_font("PrStart.ttf")


class Sound:
    def __init__(self, filename:str):
        self.sound = resource.media(filename, False)
        self.player:pyglet.media.Player|None = None
    
    def play(self):
        if not self.player:
            self.player = pyglet.media.Player()
        if self.player.playing:                
            self.player.pause()
            self.player.seek(0)
        else:
            self.player.queue(self.sound)
        self.player.play()        

class sounds:
    zap = Sound("zap.wav")
    explosion = [Sound(f"explosion ({n}).wav") for n in range(1,6)]
    oof = Sound("oof.wav")
    dud = Sound("dud.wav")

r = (-1,0,1)
rrr = tuple(product(r,r,r))

import random

class Figure:
    colors = (
            (1,0,0,1),
            (0,1,0,1),
            (0,0,1,1),
            (1,1,0,1),
            (1,0,1,1),
            (0,1,1,1),
        )

    scales=[.25,.33,.5,.66,.75,.99]
    pos:Vec3

class Cube(pyglet.model.Cube, Figure):
    def __init__(self, *a, **ka):
        size = random.choice(self.scales)
        color = random.choice(self.colors)
        super().__init__(size, size, size, color=color, batch=window.batch, group=window.group)
        
        self._size = size

class Shot(pyglet.model.Cube):
    def __init__(self, *a, camera:FPSCamera, **ka):
        super().__init__(.05, .05, 1, (255,255,255,255), batch=window.batch, group=window.group)
        self._size = .1
        self.position = Vec3(*camera.position) * Vec3(1,0.75,1)
        self._move = camera._forward*.1
        self.rotation = Mat4().rotate(
                radians(camera.yaw-90),Vec3(0,-1,0)
            ).rotate(
                radians(camera.pitch), Vec3(-1,0,0)
            ).rotate(radians(45),Vec3(0,0,1)) 
        self._timer = 600
        self.matrix = Mat4().translate(self.position) @ self.rotation

class Sphere(pyglet.model.Sphere, Figure):
    def __init__(self, *a, **ka):
        size = random.choice(self.scales)
        color = random.choice(self.colors)
        super().__init__(size, color=color, batch=window.batch, group=window.group)
        self._size = size

class Game:
    def __init__(self, window:Window, camera:FPSCamera):
        self.window = window
        self.camera = camera

        self.items = []
        self.shots = []
        self.space = {}

        self.fire_timer = 0
        self.firing = False

    def start(self):
        for _ in range(200):
            item = Cube()
            self.items.append(item)
        for _ in range(200):
            item = Sphere()
            self.items.append(item)

        for item in self.items:
            while True:
                x, z = random.randint(-24,25), random.randint(-24,25)
                if abs(x)+abs(z)<4:
                    continue
                if self.space.get((x, 0, z), None) is None:
                    item.matrix = Mat4.from_translation(Vec3(x, item._size/2, z))
                    self.space[(x, 0, z)]=item
                    item.pos = Vec3(x,item._size/2,z)
                    break

        self.floor = pyglet.model.Cube(
                50,1,50,
                color=(.5,.5,.5,1),
                batch=self.window.batch
            )
        self.floor.matrix += Mat4.from_translation(Vec3(0,-1,0))
        self.camera.game = self

    def do_shots(self):
        y:Cube|Sphere
        # a=b=0
        
        if self.shots:
            new_shots = []
            for shot in self.shots:
                for _ in range(0,5):
                    if shot.position.y<-1:
                        shot._timer=None
                        sounds.dud.play()
                        break
                    for a,b,c in rrr:
                        lx, ly, lz=round(shot.position.x)+a, round(shot.position.y)+b, round(shot.position.z)+c
                        if y:=self.space.get((lx, ly, lz), None):  # type: ignore
                            dist = shot.position.distance(y.pos)
                            if abs(dist)< y._size-shot._size:
                                y._vlist.delete()
                                self.space.pop((lx, ly, lz))
                                shot._timer=None
                                random.choice(sounds.explosion).play()
                                break
                            
                    if shot._timer:
                        shot.position += shot._move
                        shot._timer -=1
                        if not shot._timer:
                            shot._timer = None
                            break
                
                if shot._timer:
                    shot.matrix = Mat4().translate(shot.position) @ shot.rotation
                    new_shots.append(shot)
                else:
                    shot._vlist.delete()
            self.shots[:] = new_shots

        if self.firing and self.fire_timer==0:
            new_shot = Shot(camera=self.camera)
            self.fire_timer = 4
            self.shots.append(new_shot)
            sounds.zap.play()

        if self.fire_timer:
            self.fire_timer-=1

    def do_collisions(self, movement:Vec3):
        pos = camera.position
        n=0
        while n<10:
            pos += movement
            for a,b,c in rrr:
                if i:=self.space.get((round(pos.x)+a, round(pos.y)+b, round(pos.z)+c),None):
                    if i.pos.distance(pos)<i._size:
                        pos -= movement * (n+5)
                        n=10
                        sounds.oof.play()
                        break
            n+=1
        camera.position = pos

    def ground_check(self):
        if self.camera.position.y<.5:
            self.camera.position += Vec3(0,.5-self.camera.position.y,0)
        elif self.camera.position.y>.5:
            self.camera.position -= Vec3(0,self.camera.position.y-.5,0)

class FPSCamera:
    UP = Vec3(0.0, 1.0, 0.0)
    ZERO = Vec3(0.0, 0.0, 0.0)

    def __init__(
        self,
        window: Window,
        position: Vec3 | None = None,
        target: Vec3 | None = None,
        near: float = .1,
        far: float = 1000,
        field_of_view: float = 60.0,
    ) -> None:
        if not position:
            position = Vec3()
        if not target:
            target = Vec3()

        self._window:Window = weakref.proxy(window)
        self.position = position or Vec3(0.0, .5, 0.0)
        self._exclusive_mouse = False

        self.game:Game

        self._near = near
        self._far = far
        self._field_of_view = field_of_view

        self.walk_speed = 3.0
        self.look_speed = 50.0

        self._pitch = 0.0
        self._yaw = -90.0
        self._roll = 0.0
        self._elevation = 0.0
        self._forward = Vec3()

        self.keyboard_move = Vec2()
        self.mouse_look = Vec2()
        self.keyboard_look = Vec2()

        self.controller_move = Vec2()
        self.controller_look = Vec2()
        self.dead_zone = 0.1

        self._time = 0
        self._t2 = 0

        self.input_map = {
            _key.W: "forward",
            _key.S: "backward",
            _key.A: "left",
            _key.D: "right",
            _key.E: "look_up",
            _key.Q: "look_down",
            _key.LEFT: "look_left",
            _key.RIGHT: "look_right",
        }
        self.inputs = {direction: False for direction in self.input_map.values()}

        if target is None:
            target = position + Vec3(0.0, 0.0, -1.0)

        self.teleport(position, target)

        window.push_handlers(self)

    @property
    def pitch(self) -> float:
        return self._pitch
    
    @pitch.setter
    def pitch(self, value: float) -> None:
        self._pitch = clamp(value, -85.0, 85.0)

    @property
    def yaw(self) -> float:
        return self._yaw

    @yaw.setter
    def yaw(self, value: float) -> None:
        self._yaw = value

    @property
    def field_of_view(self) -> float:
        return self._field_of_view

    @field_of_view.setter
    def field_of_view(self, value: float) -> None:
        self._field_of_view = value
        self._update_projection()

    @property
    def near(self) -> float:
        return self._near

    @near.setter
    def near(self, value: float) -> None:
        self._near = value
        self._update_projection()

    @property
    def far(self) -> float:
        return self._far

    @far.setter
    def far(self, value: float) -> None:
        self._far = value
        self._update_projection()

    def on_resize(self, width: int, height: int) -> bool:
        self._window.viewport = (0, 0, *self._window.get_framebuffer_size())
        self._update_projection()
        return pyglet.event.EVENT_HANDLED

    def on_refresh(self, delta_time: float) -> None:
        self.game.do_shots()

        walk_speed = self.walk_speed * delta_time
        look_speed = self.look_speed * delta_time

        if self.mouse_look:
            self.yaw += self.mouse_look.x * look_speed
            self.pitch += self.mouse_look.y * look_speed
            self.mouse_look = Vec2()

        if self.keyboard_look:
            self.yaw += self.keyboard_look.x * look_speed
            self.pitch += self.keyboard_look.y * look_speed

        if self.controller_look:
            self.yaw += self.controller_look.x * look_speed * 20
            self.pitch += self.controller_look.y * look_speed * 20

        forward = Vec3.from_pitch_yaw(radians(self.pitch), radians(self.yaw))
        right = forward.cross(self.UP).normalize()
        up = right.cross(forward).normalize()
        translation = Vec3()

        if self.keyboard_move:
            translation += forward * self.keyboard_move.y + right * self.keyboard_move.x

        if self.controller_move:
            translation += forward * self.controller_move.y + right * self.controller_move.x

        movement = ((translation + up * self._elevation) * walk_speed)/5

        if movement:
            self.game.do_collisions(movement)
        self.game.ground_check()

        self._window.view = Mat4.look_at(self.position, self.position + forward, self.UP)
        self._forward = forward
        self._right = right
        self._up = up

        
    def on_deactivate(self) -> None:
        self.controller_look = Vec2()
        self.controller_move = Vec2()

    def teleport(self, position: Vec3, target: Vec3 | None = None) -> None:
        if target is not None:
            direction = (target - self.position).normalize()
            pitch, yaw = direction.get_pitch_yaw()
            self.yaw = degrees(yaw)
            self.pitch = degrees(pitch)

        self.position = position

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._exclusive_mouse:
            return

        self.mouse_look = Vec2(dx, dy)

    def on_mouse_press(self, x: int, y: int, button, modifiers) -> None:
        if not self._exclusive_mouse:
            self._exclusive_mouse = True
            self._window.set_exclusive_mouse(True)

        self.game.firing = True

    def on_mouse_release(self, *a):
        self.game.firing = False

    def on_key_press(self, symbol: int, mod: int) -> bool:
        if direction := self.input_map.get(symbol):
            self.inputs[direction] = True
            forward, backward, left, right, look_up, look_down, look_left, look_right = self.inputs.values()
            self.keyboard_move = Vec2(-float(left) + float(right), float(forward) + -float(backward)).normalize()
            self._elevation = float(look_up) + -float(look_down)
            self.keyboard_look = Vec2((-float(look_left)+float(look_right)) * 10, (-float(look_up)+float(look_down))*10)

            return pyglet.event.EVENT_HANDLED

        if symbol == pyglet.window.key.ESCAPE:
            if not self._exclusive_mouse:
                pyglet.app.exit()
            self._exclusive_mouse = False
            self._window.set_exclusive_mouse(False)
            return pyglet.event.EVENT_HANDLED

        elif symbol == pyglet.window.key.Z:
            self.game.firing = True

        elif symbol == pyglet.window.key.TAB:
            window.show_hud = not window.show_hud
            
        
        return False

    def on_key_release(self, symbol: int, mod: int) -> bool:
        if direction := self.input_map.get(symbol):
            self.inputs[direction] = False
            forward, backward, left, right, look_up, look_down, look_left, look_right = self.inputs.values()
            self.keyboard_move = Vec2(-float(left) + float(right), float(forward) + -float(backward)).normalize()
            self._elevation = float(look_up) + -float(look_down)
            self.keyboard_look = Vec2((-float(look_left)+float(look_right)) * 10, (-float(look_up)+float(look_down))*10)
            return pyglet.event.EVENT_HANDLED
        
        if symbol == pyglet.window.key.Z:
            self.game.firing = False

        return False

    def on_stick_motion(self, _controller, stick: str, vector: Vec2):
        if stick == "leftstick":
            if vector.length() < self.dead_zone:
                self.controller_move = Vec2()
            else:
                self.controller_move = vector

        if stick == "rightstick":
            if vector.length() >= self.dead_zone:
                self.controller_look = vector
            else:
                self.controller_look = Vec2()

    def on_trigger_motion(self, controller, trigger: str, value: float):
        if trigger == "lefttrigger":
            self._elevation = -value
        if trigger == "righttrigger":
            self._elevation = value

    def _update_projection(self):
        self._window.projection_2d = Mat4.orthogonal_projection(0, window.width, 0, window.height, -1, 1)
        self._window.projection_3d = Mat4.perspective_projection(
            window.aspect_ratio,
            z_near=camera.near,
            z_far=camera.far,
            fov=camera.field_of_view,
        )
        

class Window(pyglet.window.Window):
    def __init__(self, *a, **ka):
        config = Config(
            sample_buffers=1, samples=8, depth_size=24,
            double_buffer=True,
            debug=False,
            # vsync=False
        )
        
        super().__init__(*a, resizable=True, config=config, **ka)
        self.set_location(
        self.screen.width //2 - self.width //2,
        self.screen.height //2 - self.height //2,
        )
        self.flip()
        
        self.view: Mat4

        self.view_2d = self.view        
        self.group = pyglet.graphics.Group()
        self.batch = pyglet.graphics.Batch()
        self.batch2d = pyglet.graphics.Batch()
        self.projection_2d: Mat4
        self.projection_3d: Mat4

        self.show_hud = True

        pyglet.font.load("Press Start")

        self.label = pyglet.text.Label("Hello World", 
                                       font_name="Press Start",
                                       x=self.width//2, y=self.height-24, font_size=16, color=(210, 210, 210, 255), anchor_x='center',
                                       anchor_y='top',
                                       batch=self.batch2d)

    def on_draw(self, *a):
        self.clear()
        
        self.projection=self.projection_3d
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        self.batch.draw()
        
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        self.view = self.view_2d
        self.projection=self.projection_2d
        self.batch2d.draw()

        if self.show_hud:
            fps.draw()
            fps2.draw()
            fps3.draw()


class FPSDisplay:
    # update_period = 0.25
    label: pyglet.text.Label

    def __init__(self, hook, method, color: tuple[int, int, int, int] = (127, 127, 127, 127, ),
                 samples: int = 240, y=10, label="") -> None:
        from collections import deque
        from statistics import mean
        from time import monotonic

        from pyglet.text import Label
        self._time = monotonic
        self._mean = mean

        def wrap(fn):
            def wrapper(*a, **ka):
                start = monotonic()
                result= fn(*a, **ka)
                self.update(monotonic()-start)
                return result
            return wrapper
        
        hook2 = wrap(getattr(hook, method))
        setattr(hook, method, hook2)

        self._label =label

        self.label = Label('', x=10, y=y, font_size=24, weight='bold', color=color)
        self._delta_times = deque(maxlen=samples)
        self.counter = 0

    def update(self, t) -> None:
        """Records a new data point at the current time.

        This method is called automatically when the window buffer is flipped.
        """
        self.counter += 1
        self._delta_times.append(t)

        if self.counter==30:
            self.counter=0
            self.label.text = f'{self._label}: {self._mean(self._delta_times):.7f}'

    def draw(self) -> None:
        """Draw the label."""
        self.label.draw()


window:Window
camera:FPSCamera

def main():
    global window, camera, fps, fps2, fps3

    window = Window()
    camera = FPSCamera(window, position=Vec3(0.0, .5, 5.0))
    game = Game(window,camera)

    fps = FPSDisplay(game,"do_collisions", label="Collisions")
    fps2 = FPSDisplay(game, "do_shots", y=36, label="Shots")
    fps3 = FPSDisplay(window, "on_draw", y=64, label="Draw time")

    if controllers := pyglet.input.get_controllers():
        controller = controllers[0]
        controller.open()
        controller.push_handlers(camera)

    import gc
    gc.freeze()

    game.start()

    window.set_visible(True)
    window.flip()

    pyglet.app.run(1/60)

if __name__ == "__main__":
    main()
