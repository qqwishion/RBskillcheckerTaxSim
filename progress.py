"""Count confirmed completed races, independently of STAGE OCR or click retries."""
import json
from pathlib import Path


class RaceProgress:
    def __init__(self, path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.completed = max(0, int(data.get('completed', 0)))
        self.race_active = bool(data.get('race_active', False))
        self.result_seen = bool(data.get('result_seen', False))
        self.phase = data.get('phase', 'racing')
        self.cycles = max(0, int(data.get('cycles', 0)))

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(completed=self.completed, race_active=self.race_active,
                                              result_seen=self.result_seen, phase=self.phase,
                                              cycles=self.cycles), indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def race_visible(self):
        if self.phase != 'racing':
            return
        if not self.race_active:
            self.race_active = True
            self.result_seen = False
            self.save()

    def observe_menu(self, name):
        if name == 'START' and self.race_active and self.result_seen:
            self.race_active = self.result_seen = False
            self.save()
        if name == 'CONTINUE' and self.race_active and not self.result_seen:
            self.result_seen = True
            self.save()
        if name in ('NEXT STAGE', 'RACE', 'CASH OUT') and self.race_active and self.result_seen:
            self.completed += 1
            self.race_active = False
            self.result_seen = False
            self.save()
            return True
        return False

    def set_completed(self, count):
        self.completed = max(0, int(count))
        self.race_active = self.result_seen = False
        self.phase = 'racing'
        self.save()

    def cash_out_sent(self):
        self.phase = 'collect'
        self.race_active = self.result_seen = False
        self.save()

    def collect_sent(self):
        if self.phase != 'entry':
            self.phase = 'entry'
            self.race_active = self.result_seen = False
            self.save()

    def confirm_start(self):
        changed = self.phase != 'racing' or self.completed != 0 or self.race_active or self.result_seen
        if self.phase == 'entry':
            self.cycles += 1
        self.completed = 0
        self.race_active = self.result_seen = False
        self.phase = 'racing'
        if changed:
            self.save()
        return changed
