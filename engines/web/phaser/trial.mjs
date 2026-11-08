import {
  loadCueSheets,
  prepareCueSheets,
  spawnCueSheet,
  advanceCueSheet,
} from "./cue-sheets.mjs";
export { effectPlayback } from "./cue-sheets.mjs";

// Rules advance on a fixed game clock; presentation toggles never change contacts.
export const TRIAL = {
  ground: 356,
  hazard: [355, 425],
  package: 505,
  target: 650,
  post: 860,
  tick: 1000 / 60,
};
export function trialState(hitsToWin = 3) {
  if (!Number.isInteger(hitsToWin) || hitsToWin < 1 || hitsToWin > 20)
    throw Error("courier_trial hits_to_win must be 1..20");
  return {
    x: 150,
    y: 356,
    vy: 0,
    facing: 1,
    hp: 3,
    targetMaxHP: hitsToWin * 10,
    targetHP: hitsToWin * 10,
    lastDamage: 0,
    package: false,
    hits: 0,
    finished: false,
    lost: false,
    paused: false,
    clock: 0,
    cooldown: 0,
    freeze: 0,
    combo: 0,
    lastHit: -Infinity,
    knock: 0,
    walking: false,
    lastStep: 0,
    interactHeld: false,
    jumpHeld: false,
  };
}
export function trialStep(s, input = {}, dt = TRIAL.tick) {
  const events = [];
  if (s.paused || s.finished || s.lost) return events;
  if (s.freeze > 0) {
    s.freeze = Math.max(0, s.freeze - dt);
    return events;
  }
  s.clock += dt;
  s.cooldown = Math.max(0, s.cooldown - dt);
  const grounded = s.y >= TRIAL.ground;
  if (input.jump && !s.jumpHeld && grounded) {
    s.vy = -0.69;
    events.push("jump");
  }
  s.jumpHeld = Boolean(input.jump);
  const direction = Number(!!input.right) - Number(!!input.left);
  if (direction) s.facing = direction;
  const previousX = s.x,
    knock = s.knock;
  let next = s.x + (direction * 0.24 + s.knock) * dt;
  s.knock *= 0.78;
  if (s.targetHP > 0 && next > 600 && s.x <= 600) next = 600;
  if (s.targetHP > 0 && next < 695 && s.x >= 695) next = 695;
  s.x = Math.max(65, Math.min(900, next));
  const walking =
    direction !== 0 &&
    (s.x - previousX) * direction > 0.001 &&
    Math.abs(knock) < 0.01;
  if (walking && !s.walking) events.push("move");
  if (!walking && s.walking) events.push("stop");
  s.walking = walking;
  s.vy += 0.0019 * dt;
  s.y = Math.min(TRIAL.ground, s.y + s.vy * dt);
  if (s.y === TRIAL.ground) {
    if (!grounded) {
      events.push("land");
    }
    s.vy = 0;
  }
  if (
    s.x > TRIAL.hazard[0] &&
    s.x < TRIAL.hazard[1] &&
    s.y > 326 &&
    s.cooldown === 0
  ) {
    s.hp--;
    s.cooldown = 1100;
    s.knock = s.x < 390 ? -0.48 : 0.48;
    s.freeze = TRIAL.tick * 4;
    events.push("hurt");
    if (!s.hp) {
      s.lost = true;
      events.push("lose");
    }
  }
  if (!s.lost && !s.package && Math.abs(s.x - TRIAL.package) < 30) {
    s.package = true;
    events.push("collect");
  }
  if (s.walking && s.y === TRIAL.ground && s.clock - s.lastStep > 180) {
    s.lastStep = s.clock;
    events.push("step");
  }
  if (input.interact && !s.interactHeld && !s.lost) {
    if (s.package && s.targetHP === 0 && Math.abs(s.x - TRIAL.post) < 70) {
      s.finished = true;
      events.push("interact", "win");
    } else events.push("denied");
  }
  s.interactHeld = Boolean(input.interact);
  return events;
}

export function trialAction(s, current) {
  if (current === "attack" || current === "hurt") return current;
  if (s.y < TRIAL.ground) return current === "jump" ? "jump" : "idle";
  return s.walking ? "walk" : "idle";
}

export function trialHit(s, contact) {
  if (!contact || s.targetHP === 0 || s.finished || s.lost || s.paused)
    return [];
  s.combo = s.clock - s.lastHit < 1800 ? s.combo + 1 : 1;
  s.lastHit = s.clock;
  s.hits++;
  s.lastDamage = Math.min(s.targetHP, s.combo === 2 ? 15 : 10);
  s.targetHP -= s.lastDamage;
  s.freeze = TRIAL.tick * 4;
  return [s.targetHP === 0 ? "finisher" : s.combo === 2 ? "crit" : "hit"];
}

export function courierScene({ Phaser, bundle, meta, ActionActor, feedback }) {
  for (const [key, value] of Object.entries({ target_x: 650, target_y: 300 }))
    if (bundle.playtest?.[key] !== undefined && bundle.playtest[key] !== value)
      throw Error(`courier_trial requires ${key}=${value}`);
  return class CourierTrial extends Phaser.Scene {
    preload() {
      this.load.image("actor", bundle.files.atlas);
      (meta.events || []).forEach((e, i) =>
        this.load.image(`effect-${i}`, bundle.files[`effect_${i}_sheet`]),
      );
      loadCueSheets(this, bundle.feedback?.effects);
    }
    create(data) {
      this.state = trialState(bundle.playtest?.hits_to_win ?? 3);
      this.hits = 0;
      this.finished = false;
      this.contactEvents = [];
      this.accumulator = 0;
      this.pending = {};
      this.cues = [];
      this.cueEvents = [];
      this.trail = 3;
      this.trailDelay = 0;
      this.targetTrail = this.state.targetMaxHP;
      this.targetTrailDelay = 0;
      this.fxEnabled =
        document.querySelector("#feel").getAttribute("aria-pressed") !==
        "false";
      this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.getElementById("pause").textContent = "잠시 멈춤 · P";
      this.paintWorld();
      this.actor = new ActionActor(
        this,
        meta,
        "actor",
        150,
        356,
        144 / meta.actions.idle.frames[0].rect.w,
      );
      this.actor.effectsEnabled = this.fxEnabled;
      this.hpBar = this.add.graphics().setDepth(21);
      for (const [i, e] of (meta.events || []).entries())
        e.frames.forEach((f, n) =>
          this.textures
            .get(`effect-${i}`)
            .add(String(n), 0, f.rect.x, f.rect.y, f.rect.w, f.rect.h),
        );
      this.sheetBindings = prepareCueSheets(this, bundle.feedback?.effects);
      this.shadow = this.add.ellipse(150, 360, 76, 12, 0x142b2d).setAlpha(0.6);
      this.actor.sprite.setDepth(5);
      this.hud = this.add
        .text(30, 24, "", {
          fontFamily: "system-ui",
          fontSize: "19px",
          color: "#fff1d0",
        })
        .setDepth(20);
      this.banner = this.add
        .text(480, 150, "", {
          fontFamily: "system-ui",
          fontSize: "30px",
          color: "#fff1d0",
          align: "center",
        })
        .setOrigin(0.5)
        .setDepth(25);
      this.keys = this.input.keyboard.addKeys(
        "LEFT,RIGHT,A,D,SPACE,W,UP,E,P,ESC,R",
      );
      this.input.keyboard.addCapture(["LEFT", "RIGHT", "SPACE", "UP"]);
      this.input.keyboard.on("keydown", (e) => {
        if (e.repeat || e.target.closest?.("button")) return;
        feedback.setSound(feedback.sound);
        if (e.code === "KeyR") this.restart();
        if (e.code === "KeyP" || e.code === "Escape") this.pause();
        if (e.code === "Space") this.strike();
        if (e.code === "KeyW" || e.code === "ArrowUp") this.pending.jump = true;
        if (e.code === "KeyE") this.pending.interact = true;
      });
      this.touch = { left: false, right: false };
      for (const name of ["left", "right"]) {
        const b = document.getElementById(name);
        let start = null;
        b.onpointerdown = (e) => {
          e.preventDefault();
          b.setPointerCapture(e.pointerId);
          start = this.state.x;
          this.touch[name] = true;
          feedback.setSound(feedback.sound);
        };
        b.onpointerup = () => {
          this.touch[name] = false;
          start = null;
        };
        b.onpointercancel = () => {
          this.touch[name] = false;
          start = null;
        };
        b.onclick = (e) => {
          if (e.detail === 0) {
            this.touch[name] = true;
            this.time.delayedCall(100, () => (this.touch[name] = false));
          }
        };
      }
      for (const [id, fn] of Object.entries({
        attack: () => this.strike(),
        jump: () => (this.pending.jump = true),
        interact: () => (this.pending.interact = true),
        pause: () => this.pause(),
        restart: () => this.restart(),
      }))
        document.getElementById(id).onclick = () => {
          feedback.setSound(feedback.sound);
          fn();
        };
      document.getElementById("feel").onclick = () => {
        this.fxEnabled = !this.fxEnabled;
        this.actor.effectsEnabled = this.fxEnabled;
        document
          .getElementById("feel")
          .setAttribute("aria-pressed", String(this.fxEnabled));
        document.getElementById("feel").textContent =
          `손맛 ${this.fxEnabled ? "켜짐" : "꺼짐"} · A/B`;
        feedback.setEnabled?.(this.fxEnabled);
        if (!this.fxEnabled) {
          this.cues.forEach((c) => c.object.destroy());
          this.cues = [];
          this.actor.effects.forEach((c) => c.image.destroy());
          this.actor.effects = [];
          this.flashUntil = 0;
        }
      };
      document.getElementById("sound").onclick = () => {
        feedback.setSound(feedback.sound);
        const b = document.getElementById("sound"),
          on = b.getAttribute("aria-pressed") !== "true";
        b.setAttribute("aria-pressed", String(on));
        b.textContent = `소리 ${on ? "켜짐" : "꺼짐"}`;
        feedback.setSound?.(on);
      };
      window.onblur = () => {
        this.touch.left = this.touch.right = false;
        if (!this.state.paused && !this.state.finished && !this.state.lost)
          this.pause();
      };
      this.game.canvas.setAttribute("aria-hidden", "true");
      this.message("틈을 뛰어넘고 → 우편 수집 → 나무 장벽 타격 → 우체통에 E");
      this.refresh();
      if (data?.restarted) this.cue("restart");
    }
    paintWorld() {
      const g = this.add.graphics();
      g.fillStyle(0x15373c).fillRect(0, 0, 960, 540);
      g.fillStyle(0x235056).fillCircle(780, 85, 160);
      g.fillStyle(0xf7d58b).fillCircle(785, 85, 32);
      for (let i = 0; i < 12; i++) {
        const x = i * 91;
        g.fillStyle(0x193f3e).fillRect(x, 150 + (i % 3) * 20, 20, 205);
        g.fillStyle(0x2d5b4b).fillTriangle(
          x - 50,
          220,
          x + 10,
          80,
          x + 70,
          220,
        );
      }
      g.fillStyle(0x4d6550).fillRect(0, 358, 960, 182);
      g.fillStyle(0xb0a275).fillRect(0, 356, 960, 9);
      g.fillStyle(0x74816a).fillRect(0, 380, 960, 16);
      for (let i = 0; i < 55; i++)
        g.fillStyle(i % 2 ? 0x789074 : 0x405b4a).fillRect(
          (i * 137) % 960,
          410 + ((i * 19) % 120),
          12,
          3,
        );
      g.fillStyle(0x162d31).fillRect(350, 357, 80, 38);
      for (let x = 358; x < 426; x += 16)
        g.fillStyle(0xe39b72).fillTriangle(x, 359, x + 8, 336, x + 16, 359);
      this.barrierLabel = this.add.text(0, -27, "", {
        fontSize: "18px",
        color: "#fff1d0",
      }).setOrigin(0.5);
      this.target = this.add.container(650, 305, [
        this.add.rectangle(0, 0, 44, 98, 0xa87945).setStrokeStyle(4, 0xe0b879),
        this.add.rectangle(0, 8, 62, 12, 0x66472f),
        this.barrierLabel,
      ]);
      this.parcel = this.add.container(505, 325, [
        this.add.rectangle(0, 0, 28, 24, 0xf3cf85).setStrokeStyle(3, 0x96663d),
        this.add.rectangle(0, 0, 5, 24, 0xd68b60),
        this.add.rectangle(0, -4, 28, 4, 0xd68b60),
      ]);
      g.fillStyle(0x7e583c).fillRect(851, 305, 18, 51);
      g.fillStyle(0xc36d52).fillRoundedRect(829, 265, 62, 47, 7);
      g.fillStyle(0x302e32).fillRect(839, 280, 42, 7);
      g.fillStyle(0xffdfa1).fillRect(840, 295, 10, 6);
      for (const [x, text] of [
        [180, "출발"],
        [390, "W / ↑ 점프"],
        [505, "우편"],
        [650, "SPACE 타격"],
        [860, "E 배송"],
      ])
        this.add
          .text(x, 395, text, {
            fontSize: "15px",
            fontFamily: "system-ui",
            color: "#fff1d0",
          })
          .setOrigin(0.5);
    }
    message(text) {
      document.getElementById("status").textContent = text;
    }
    restart() {
      this.touch.left = this.touch.right = false;
      this.scene.restart({ restarted: true });
    }
    pause() {
      if (this.state.finished || this.state.lost) return;
      this.state.paused = !this.state.paused;
      this.pending = {};
      this.touch.left = this.touch.right = false;
      this.cue(this.state.paused ? "pause" : "resume");
      document.getElementById("pause").textContent = this.state.paused
        ? "계속 · P"
        : "잠시 멈춤 · P";
      this.refresh();
    }
    strike() {
      if (
        this.state.paused ||
        this.state.finished ||
        this.state.lost ||
        this.actor.action === "attack"
      )
        return;
      this.actor.play("attack");
      this.cue("attack");
    }
    cue(event, x = this.state.x, y = this.state.y) {
      this.cueEvents.push({ event, clock: this.state.clock, x, y });
      if (this.cueEvents.length > 120) this.cueEvents.shift();
      if (event === "collect") this.parcel.setVisible(false);
      if (event === "finisher") this.target.setVisible(false);
      if (event === "hurt") this.trailDelay = this.time.now + 300;
      if (event === "hurt")
        this.message(`가시에 닿았어요 · 체력 ${this.state.hp}/3 · W로 도약`);
      if (event === "denied")
        this.message(
          "우편과 장벽 제거가 필요해요. 우체통 가까이에서 E를 누르세요.",
        );
      if (event === "collect")
        this.message("우편 획득! 앞의 장벽을 SPACE로 타격하세요.");
      if (event === "finisher")
        this.message("길이 열렸어요! 오른쪽 우체통에 E로 배송하세요.");
      if (event === "win")
        this.message("배송 완료! R로 다시 시작할 수 있어요.");
      if (event === "lose") this.message("배송 실패 · R로 다시 도전하세요.");
      if (!this.fxEnabled) return;
      this.lastFeedback = feedback.emit?.(
        { collect: "pickup", finisher: "finish" }[event] || event,
        { combo: this.state.combo, facing: this.state.facing },
      );
      const impact = ["hit", "crit", "finisher", "hurt"].includes(event);
      if (impact && event !== "hurt")
        this.targetTrailDelay = this.time.now + 300;
      if (impact) {
        const obj = event === "hurt" ? this.actor.sprite : this.target;
        obj.list?.forEach((o) => {
          if (o.fillColor !== undefined) {
            o.originalFill = o.fillColor;
            o.setFillStyle(0xffffff);
          } else o.setTint?.(0xffffff);
        });
        if (event === "hurt") obj.setTintFill(0xffffff);
        this.flashUntil = this.time.now + 70;
        this.flashObject = obj;
      }
      const cueName = { collect: "pickup", finisher: "finish" }[event] || event;
      const mapped = spawnCueSheet(this, this.sheetBindings, cueName, {
        x,
        y,
        facing: this.state.facing,
        reducedMotion: this.reduced,
      });
      if (mapped) this.cues.push(mapped);
      if (!this.reduced) {
        if (
          impact ||
          [
            "jump",
            "land",
            "collect",
            "interact",
            "denied",
            "win",
            "lose",
            "move",
          ].includes(event)
        ) {
          if (impact && event !== "hurt") {
            this.targetKickUntil = this.time.now + 120;
            this.targetKickSign = this.state.facing;
          }
          const color =
            event === "hurt"
              ? 0xffb08a
              : event === "denied"
                ? 0xf0ab83
                : 0xffe4a0;
          const object = this.add.graphics().setDepth(9);
          const sign = this.state.facing;
          if (impact) {
            object
              .lineStyle(4, color)
              .beginPath()
              .arc(x, y - 30, 28, sign > 0 ? -1.3 : 1.8, sign > 0 ? 1.3 : 4.5)
              .strokePath();
            for (let i = 0; i < (event === "finisher" ? 12 : 6); i++) {
              const a = i * 2.4;
              object
                .fillStyle(color)
                .fillRect(
                  x + Math.cos(a) * 24,
                  y - 30 + Math.sin(a) * 24,
                  5 + (i % 3),
                  4,
                );
            }
          } else
            object
              .lineStyle(3, color)
              .strokeEllipse(x, y + 2, event === "land" ? 70 : 35, 12);
          this.cues.push({
            object,
            elapsed: 0,
            duration: impact ? 220 : 280,
            sign: impact ? sign : 0,
          });
        }
        if (event === "hurt" || event === "jump" || event === "land") {
          this.squashUntil = this.time.now + 130;
          this.squash = event === "jump" ? [0.9, 1.12] : [1.15, 0.85];
        }
      }
      if (impact || event === "collect") {
        const text =
          event === "hurt"
            ? "−1 ♥"
            : event === "collect"
              ? "+ 우편"
              : event === "finisher"
                ? `길 개방! −${this.state.lastDamage}`
                : event === "crit"
                  ? `치명타! −${this.state.lastDamage}`
                  : `−${this.state.lastDamage}`;
        const object = this.add
          .text(x, y - 100, text, {
            fontSize: "22px",
            fontFamily: "system-ui",
            color: "#fff1d0",
            stroke: "#233638",
            strokeThickness: 4,
          })
          .setOrigin(0.5)
          .setDepth(12);
        this.cues.push({ object, elapsed: 0, duration: 700, text: true });
      }
    }
    refresh() {
      const s = this.state;
      this.barrierLabel.setText(`HP ${s.targetHP}`);
      this.hits = s.hits;
      this.finished = s.finished;
      this.hud.setText(
        `♥ ${s.hp}/3    우편 ${s.package ? "✓" : "○"}    장벽 HP ${s.targetHP}/${s.targetMaxHP} · 명중 ${s.hits}`,
      );
      this.banner.setText(
        s.lost
          ? "배송 실패\nR · 다시 도전"
          : s.finished
            ? "배송 완료!\nR · 한 번 더"
            : s.paused
              ? "잠시 쉬는 중\nP · 계속"
              : "",
      );
    }
    update(time, delta) {
      if (!this.actor) return;
      this.reduced = feedback.reducedMotion;
      const s = this.state;
      this.accumulator += Math.min(delta, 100);
      while (this.accumulator >= TRIAL.tick) {
        this.accumulator -= TRIAL.tick;
        const left =
            this.touch.left || this.keys.LEFT.isDown || this.keys.A.isDown,
          right =
            this.touch.right || this.keys.RIGHT.isDown || this.keys.D.isDown;
        const frozen = s.freeze > 0,
          stopped = s.paused || s.finished || s.lost;
        const events = trialStep(s, {
          left,
          right,
          ...this.pending,
        });
        if (!frozen && !stopped) this.pending = {};

        this.actor.x = s.x;
        this.actor.y = s.y;
        this.actor.facing = s.facing;
        for (const event of events) {
          if ((event === "jump" || event === "hurt") && meta.actions[event])
            this.actor.play(event);
          this.cue(event);
        }
        if ((!stopped && !frozen) || (s.lost && this.actor.action === "hurt")) {
          const action = trialAction(s, this.actor.action);
          if (this.actor.action !== action) this.actor.play(action);
          this.actor.update(TRIAL.tick, (event, point, elapsed) => {
            if (event.action !== "attack") return;
            const contact =
              s.targetHP > 0 &&
              (650 - s.x) * s.facing > 0 &&
              Math.abs(point.x - 650) < 62 &&
              Math.abs(point.y - 300) < 74;
            this.contactEvents.push({
              start_ms: event.start_ms,
              observed_ms: elapsed,
              point,
              contact,
            });
            for (const e of trialHit(s, contact)) this.cue(e, 650, 330);
            if (!contact) this.cue("miss", point.x, point.y);
          });
        }
      }
      this.shadow
        .setPosition(s.x, 360)
        .setScale(Math.max(0.35, 1 - (356 - s.y) / 250));
      if (time > this.flashUntil) {
        this.flashObject?.clearTint?.();
        this.flashObject?.list?.forEach((o) => {
          if (o.originalFill !== undefined) o.setFillStyle(o.originalFill);
          else o.clearTint?.();
        });
        this.flashObject = null;
      }
      const kicked =
        this.fxEnabled && !this.reduced && time < this.targetKickUntil;
      this.target
        .setPosition(650 + (kicked ? this.targetKickSign * 7 : 0), 305)
        .setScale(kicked ? 1.13 : 1, kicked ? 0.88 : 1);
      const squash =
        this.fxEnabled && !this.reduced && time < this.squashUntil
          ? this.squash
          : [1, 1];
      this.actor.sprite.setScale(
        this.actor.scale * squash[0],
        this.actor.scale * squash[1],
      );
      this.cues = this.cues.filter((c) => {
        if (c.frames) return advanceCueSheet(c, delta, this.reduced);
        c.elapsed += delta;
        c.object.setAlpha(Math.max(0, 1 - c.elapsed / c.duration));
        if (!this.reduced) {
          if (c.text) c.object.y -= delta * 0.025;
          if (c.sign) c.object.x += c.sign * delta * 0.06;
        }
        if (c.elapsed >= c.duration) {
          c.object.destroy();
          return false;
        }
        return true;
      });
      if (time > this.targetTrailDelay)
        this.targetTrail +=
          (s.targetHP - this.targetTrail) * Math.min(1, delta * 0.005);
      if (time > this.trailDelay)
        this.trail += (s.hp - this.trail) * Math.min(1, delta * 0.005);
      this.hpBar
        .clear()
        .fillStyle(0x273d3c)
        .fillRect(30, 57, 150, 7)
        .fillStyle(0xf2be83)
        .fillRect(30, 57, (this.fxEnabled ? this.trail : s.hp) * 50, 7)
        .fillStyle(0x8dc6a1)
        .fillRect(30, 57, s.hp * 50, 7);
      if (s.targetHP > 0 || this.targetTrail > 1)
        this.hpBar
          .fillStyle(0x273d3c)
          .fillRect(605, 235, 90, 7)
          .fillStyle(0xf2be83)
          .fillRect(
            605,
            235,
            ((this.fxEnabled ? this.targetTrail : s.targetHP) / s.targetMaxHP) *
              90,
            7,
          )
          .fillStyle(0xa5c9a2)
          .fillRect(605, 235, (s.targetHP / s.targetMaxHP) * 90, 7);
      this.refresh();
    }
  };
}
