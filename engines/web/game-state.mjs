export const CRYSTALS = [[-3, 2], [3, 1], [-2, -3]];
export const GOAL = [1, -2];
export const ATTACK_RANGE = 1.45;
export function createGame() {
  return { x: 0, z: 4, collected: CRYSTALS.map(() => false), charge: 0, won: false,
    attackAt: -Infinity, message: 'Collect the three blue crystals.' };
}
export function move(game, x, z, seconds) {
  if (game.won) return;
  const length = Math.hypot(x, z);
  if (length) {
    game.x = Math.max(-5, Math.min(5, game.x + x / length * seconds * 3));
    game.z = Math.max(-4.5, Math.min(5, game.z + z / length * seconds * 3));
  }
  CRYSTALS.forEach(([cx, cz], i) => {
    if (!game.collected[i] && Math.hypot(game.x - cx, game.z - cz) < .65) {
      game.collected[i] = true;
      game.message = game.collected.every(Boolean) ? 'Return to the lantern. Attack three times to restore its light.' : 'Crystal collected. Find the remaining blue crystals.';
    }
  });
}
export function attack(game, now) {
  if (game.won || now - game.attackAt < .4) return false;
  game.attackAt = now;
  if (Math.hypot(game.x - GOAL[0], game.z - GOAL[1]) > ATTACK_RANGE) {
    game.message = 'Too far away. Move closer to the lantern.';
    return false;
  }
  if (!game.collected.every(Boolean)) {
    game.message = 'The lantern needs all three crystals first.';
    return false;
  }
  game.charge += 1;
  game.won = game.charge === 3;
  game.message = game.won ? 'The woods are alight again. You restored the lantern!' : `Light restored: ${game.charge}/3. Strike again.`;
  return true;
}
