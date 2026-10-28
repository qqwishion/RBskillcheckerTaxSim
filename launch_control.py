"""Adaptive throttle pulses; cyan needle samples define the launch target."""


class LaunchController:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.velocity = 0.
        self.up_rate = self.down_rate = 300.
        self.target = None
        self.phase = .5
        self.held = False
        self.switched_at = 0.

    def update(self, angle, low, high, color, now):
        if self.previous and now-self.previous[1] > .25:
            self.reset()
        if self.target is None or not low <= self.target <= high:
            self.target = (low+high)/2
        if self.previous:
            dt = now-self.previous[1]
            if .001 < dt < .25:
                raw = max(-1500., min(1500., (angle-self.previous[0])/dt))
                self.velocity = .55*self.velocity+.45*raw
                if now-self.switched_at > .025:
                    if self.held and raw > 20:
                        self.up_rate = .9*self.up_rate+.1*raw
                    elif not self.held and raw < -20:
                        self.down_rate = .9*self.down_rate-.1*raw
        self.previous = (angle, now)
        if color == 'cyan' and low <= angle <= high:
            self.target = .8*self.target+.2*angle
        total_rate = max(80., self.up_rate+self.down_rate)
        neutral = self.down_rate/total_rate
        error = self.target-angle
        duty = max(0., min(1., neutral + error/max(3., total_rate*.035) - .65*self.velocity/total_rate))
        if angle < low-10:
            down = True
        elif angle > high+3:
            down = False
        else:
            self.phase += duty
            down = self.phase >= 1.
            if down:
                self.phase -= 1.
        if down != self.held and now-self.switched_at >= .014:
            self.held = down
            self.switched_at = now
        return self.held
