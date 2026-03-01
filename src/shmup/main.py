from __future__ import annotations

import pyglet
pyglet.options.debug_gl=False
pyglet.options.vsync=False

import weakref
import gc

from math import radians, degrees

from pyglet.gl import glEnable, glDisable, GL_DEPTH_TEST, GL_CULL_FACE, Config
from pyglet.math import Vec2, Vec3, Mat4, clamp
from pyglet.window import key as _key

from itertools import product
from collections import deque
from typing import Callable
from statistics import mean
from time import monotonic

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

    scales=[.25,.33,.5,.66,.75,1]
    
    pos:Vec3
    matrix:Mat4

    _rotation:Mat4
    _move:Vec3
    _size:float
    _vlist:object

    _window:Window
    _game:Game

    def update(self):
        self.matrix = Mat4().translate(self.pos) @ self._rotation

    def move(self):
        self.pos += self._move

    def set_pos(self, pos:Vec3):        
        self.pop_space()
        self.pos = pos
        self.matrix = Mat4.from_translation(Vec3(pos.x, self._size/2, pos.z))
        self._game.space[(pos.x, 0, pos.z)]=self
        self.set_min_max()
        self._halfsize = self._size/2

    def set_min_max(self):
        pos=self.pos
        self._min = Vec3(pos.x-self._halfsize,pos.y-self._halfsize,pos.z-self._halfsize)
        self._max = Vec3(pos.x+self._halfsize,pos.y+self._halfsize,pos.z+self._halfsize)

    def collide(self, other:Figure):
        raise NotImplementedError
    
    def pop_space(self):
        self._game.space.pop(
            (round(self.pos.x), round(self.pos.y), round(self.pos.z)), None
        )
    def delete(self):
        self.pop_space()
        self._vlist.delete() # type: ignore

    def set_random_position(self, camera):
        while True: 
            x, z = random.randint(-24,25), random.randint(-24,25)
            if abs(x-camera.position.x)+abs(z-camera.position.y)<2:
                continue
            if self._game.space.get((x, 0, z), None) is None:
                self.set_pos(Vec3(x, self._size/2, z))
                break

class Cube(pyglet.model.Cube, Figure):
    def __init__(self, *a, **ka):
        size = random.choice(self.scales)
        color = random.choice(self.colors)
        super().__init__(size, size, size, color=color, batch=self._window.batch, group=self._window.group)
        self._size = size
        self._halfsize = size/2
        self.pos = Vec3()
    
    def collide(self, other:Figure):
        pos:Vec3 = other.pos
        half = other._halfsize
        return (
            self._min.x-half <= pos.x <= self._max.x+half and
            self._min.y-half <= pos.y <= self._max.y+half and
            self._min.z-half <= pos.z <= self._max.z+half
            )
    
class Shot(pyglet.model.Cube, Figure):
    def __init__(self, *a, camera:FPSCamera, **ka):
        super().__init__(.05, .05, 1, (255,255,255,255), batch=self._window.batch, group=self._window.group)
        self._size = .1
        self.pos = Vec3(*camera.position) * Vec3(1,0.75,1)
        self._move = camera._forward*.25
        self._rotation = Mat4().rotate(
                radians(camera.yaw-90),Vec3(0,-1,0)
            ).rotate(
                radians(camera.pitch), Vec3(-1,0,0)
            ).rotate(radians(45),Vec3(0,0,1)) 
        self._timer = 200
        self.matrix = Mat4().translate(self.pos) @ self._rotation
        self._halfsize = .05

class Sphere(pyglet.model.Sphere, Figure):
    def __init__(self, *a, **ka):
        size = random.choice(self.scales)
        color = random.choice(self.colors)
        super().__init__(size, color=color, batch=self._window.batch, group=self._window.group)
        self._size = size
        self._halfsize = size/2
        self.pos = Vec3()

    def collide(self, other:Figure):
        return self.pos.distance(other.pos)<(self._halfsize+other._size/2)

class GameMode:
    space:dict

class Game(GameMode):
    def __init__(self, window:Window, camera:FPSCamera):
        self.window = window
        self.camera = camera
        
        self.camera.game = self
        Figure._game = self
        Figure._window = window

        self.items = []
        self.shots = []
        self.new_shots = []
        self.space = {}

        self.show_hud = True

        self.fire_timer = 0
        self.firing = False

        self.oof_pos = Vec3()
        
        if controllers := pyglet.input.get_controllers():
            controller = controllers[0]
            controller.open()
            controller.push_handlers(camera)
        
        self.fps1, self.do_collisions = FPSDisplay.hook(self.do_collisions, label="Collisions")
        self.fps2, self.do_shots = FPSDisplay.hook(self.do_shots, y=40, label="Shots")
        self.fps3, self.on_draw_ = FPSDisplay.hook(self.on_draw_,y=72, label="Draw time")

        self.fps = (self.fps1, self.fps2, self.fps3)

        # self.on_draw is a method pushed as a handler, so we cannot wrap it directly.
        # This is a Pyglet behavior, not a Python thing!

        window.push_handlers(self)


    def enter(self):
        for _ in range(200):
            item = Cube()
            self.items.append(item)
        for _ in range(200):
            item = Sphere()
            self.items.append(item)

        for item in self.items:
            item.set_random_position(self.camera)

        self.floor = pyglet.model.Cube(
                50,1,50,
                color=(.5,.5,.5,1),
                batch=self.window.batch
            )
        self.floor.matrix += Mat4.from_translation(Vec3(0,-1,0))

        self.label = pyglet.text.Label("Shoot everything!", 
            font_name="Press Start",
            x=self.window.width//2, y=self.window.height-24,
            font_size=16, color=(210, 210, 210, 255), anchor_x='center',
            anchor_y='top',
            batch=self.window.batch2d
        )
        
        self.reticle = pyglet.shapes.Box(
            self.window.width//2 - 64,
            self.window.height//2 - 64,
            128, 128, color=(255,255,255,64),
            thickness=8,
            batch=self.window.batch2d
        )
        

    def do_shots(self):
        y:Figure
        gc.disable()
        if self.shots:
            self.new_shots[:] = []
            for shot in self.shots:
                for _ in range(0,2):
                    if shot.pos.y<0:
                        shot._timer=None
                        sounds.dud.play()
                        break
                    for a,b,c in rrr:
                        lx, ly, lz=round(shot.pos.x)+a, round(shot.pos.y)+b, round(shot.pos.z)+c
                        if y:=self.space.get((lx, ly, lz), None):  # type: ignore
                            if y.collide(shot):
                                y.delete()
                                # self.space.pop((lx, ly, lz))
                                shot._timer=None
                                random.choice(sounds.explosion).play()
                                new = y.__class__()
                                new.set_random_position(self.camera)
                                self.items.append(new)
                                break
                            
                    if shot._timer:
                        shot.move()
                        shot._timer -=1
                        if not shot._timer:
                            shot._timer = None
                            break
                
                if shot._timer:
                    shot.update()
                    self.new_shots.append(shot)
                else:
                    shot._vlist.delete()
            self.shots[:] = self.new_shots
            self.new_shots[:] = []

        if self.firing and self.fire_timer==0:
            new_shot = Shot(camera=self.camera)
            self.fire_timer = 4
            self.shots.append(new_shot)
            sounds.zap.play()

        if self.fire_timer:
            self.fire_timer-=1

    def do_collisions(self, movement:Vec3):
        pos = Vec3(*self.camera.position)
        for _ in range(10):
            pos += movement
            for a,b,c in rrr:
                if i:=self.space.get((round(pos.x)+a, round(pos.y)+b, round(pos.z)+c),None):
                    if i.pos.distance(pos)<i._size:
                        pos -= movement
                        if self.oof_pos != pos:
                            sounds.oof.play()
                        self.oof_pos = Vec3(*pos)
                        return 
            self.camera.position = pos

    def ground_check(self):
        if self.camera.position.y<.5:
            self.camera.position += Vec3(0,.5-self.camera.position.y,0)
        elif self.camera.position.y>.5:
            self.camera.position -= Vec3(0,self.camera.position.y-.5,0)
        gc.enable()

    def on_draw(self, *a):
        return self.on_draw_(self, *a)

    def on_draw_(self, *a):
        w = self.window
        w.clear()
        w.projection=w.projection_3d
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        w.batch.draw()
        
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        w.view = w.view_2d
        w.projection=w.projection_2d
        w.batch2d.draw()

        if self.show_hud:
            for _ in self.fps: _.draw()

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
        self._update_projection()

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

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        self.field_of_view = clamp(self.field_of_view - scroll_y*5, 10, 60 )
        self.look_speed = clamp(self.look_speed - scroll_y*5, 10, 50 )

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
            return pyglet.event.EVENT_HANDLED

        elif symbol == pyglet.window.key.TAB:
            self.game.show_hud = not self.game.show_hud
            return pyglet.event.EVENT_HANDLED
        
        if mod == pyglet.window.key.MOD_CAPSLOCK:
            self.look_speed = 10 if self.look_speed==50 else 50
            self.field_of_view = 10 if self.field_of_view==60 else 60
            return pyglet.event.EVENT_HANDLED
        
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
            return pyglet.event.EVENT_HANDLED
        
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
        self._window.projection_2d = Mat4.orthogonal_projection(0, self._window.width, 0, self._window.height, -1, 1)
        self._window.projection_3d = Mat4.perspective_projection(
            self._window.aspect_ratio,
            z_near=self.near,
            z_far=self.far,
            fov=self.field_of_view,
        )

class Window(pyglet.window.Window):
    def __init__(self, *a, **ka):
        config = Config(
            sample_buffers=1, samples=8, depth_size=24,
            double_buffer=True,
            debug=False,
        )
        
        super().__init__(*a, resizable=True, config=config, **ka)
        self.set_location(
        self.screen.width //2 - self.width //2,
        self.screen.height //2 - self.height //2,
        )
        self.flip()
        
        self.view: Mat4

        self.view_2d = self.view        
        self.group = pyglet.graphics.Group(0)
        self.group1 = pyglet.graphics.Group(1)

        self.batch = pyglet.graphics.Batch()
        self.batch2d = pyglet.graphics.Batch()
        self.projection_2d = Mat4.orthogonal_projection(0, self.width, 0, self.height, -1, 1)
        self.projection_3d = Mat4()

        pyglet.font.load("Press Start")


class FPSDisplay:
    # update_period = 0.25
    label: pyglet.text.Label
    _time: float
    _mean: Callable
    _label: str
    _delta_times: deque

    @classmethod
    def hook(cls, hook, color: tuple[int, int, int, int] = (127, 127, 127, 127, ),
                 samples: int = 240, y=10, label="") :
        
        self = cls()
        self._time = 0
        self._mean = mean
        self._label =label

        def wrap(fn):
            def wrapper(*a, **ka):
                start = monotonic()
                result= fn(*a, **ka)
                self.update(monotonic()-start)
                return result
            return wrapper
        
        new_fn = wrap(hook)

        self.label = pyglet.text.Label('', x=10, y=y, font_size=24, weight='bold', color=color)
        self._delta_times = deque(maxlen=samples)
        self.counter = 0

        return self, new_fn

    def update(self, t) -> None:
        self.counter += 1
        self._delta_times.append(t)

        if self.counter==30:
            self.counter=0
            self.label.text = f'{self._label}: {self._mean(self._delta_times):.7f}'

    def draw(self) -> None:
        self.label.draw()

class ClickLabel(pyglet.gui.WidgetBase):
    click: Callable
    def __init__(self, text, font_name, x, y, window, font_size=16, color=(255,255,255,255), anchor_x="center", anchor_y="center", click=None):
        self.window=window
        
        self.label = pyglet.text.Label(text,font_name = font_name, font_size=font_size, color=color, x=x, y=y, batch=self.window.batch2d, group=self.window.group1, anchor_x="center", anchor_y="center", width=self.window.width, multiline=True, align="center")

        print (self.label.content_width, self.label.content_height)
        
        super().__init__(x=int(self.label.x-self.label.content_width//2), y=int(self.label.bottom), width=self.label.content_width, height=self.label.content_height)
        
        if click:
            self.click = click

        self.hover = False
        
    def on_mouse_motion(self, x, y, *a):
        hit = self._check_hit(x, y)
        if self.hover:
            if not hit:
                self.hover=False
                self.label.color=255,255,255,127
                
        else:
            if hit:
                self.hover=True
                self.label.color=255,255,255,255

    def on_mouse_press(self, x, y, *a):
        if self.hover:            
            self.click()
    
    def delete(self):
        self.label.delete()
        

class WelcomeScreen(GameMode):
    def __init__(self, window):
        self.window=window

    def on_draw(self, *a):       
        self.window.clear()
        self.window.batch2d.draw()
        return True

    def on_key_press(self, symbol: int, mod: int) -> bool:
        if symbol == pyglet.window.key.SPACE:
            self.exit()
        return True

    def exit(self):
        self.label.label.text="One sec ..."        
        
        self.on_draw()
        self.window.flip()
        
        self.window.pop_handlers()
        self.window.pop_handlers()

        camera = FPSCamera(self.window, position=Vec3(0.0, .5, 5.0))
        mode = Game(self.window, camera)
        mode.enter()

        camera._exclusive_mouse=True
        self.window.set_exclusive_mouse(True)

        self.label.delete()

    def enter(self):
        self.label = ClickLabel(
            "Click here to start",
            font_name="Press Start",
            x=self.window.width//2, y=self.window.height//2,
            window=self.window,
            font_size=16, color=(255, 255, 255, 127),
            click = self.exit
        )

        self.window.push_handlers(self.label)
        self.window.push_handlers(self)


def main():
    window = Window()    
    mode = WelcomeScreen(window)

    mode.enter()

    window.set_visible(True)
    window.flip()

    pyglet.app.run()

if __name__ == "__main__":
    main()

