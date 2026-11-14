import * as THREE from 'three';
import {
  makeAsphaltTexture,
  makeConcreteTexture,
  makeFurTexture,
  makeGrassTexture,
  makeNoiseTexture,
} from './textures.js';

function skinMat(hex = 0x1a2438) {
  return new THREE.MeshStandardMaterial({
    color: hex,
    emissive: 0x0a1528,
    emissiveIntensity: 0.35,
    roughness: 0.72,
    metalness: 0.05,
  });
}

function clothMat(hex, emissive = 0x081018) {
  return new THREE.MeshStandardMaterial({
    color: hex,
    emissive,
    emissiveIntensity: 0.25,
    roughness: 0.8,
    metalness: 0.08,
  });
}

/** Более читаемый человечек: шея, бёдра, куртка, кроссовки + слот под наушники */
export function createFigure() {
  const root = new THREE.Group();
  const skin = skinMat(0x2a3448);
  const jacket = clothMat(0x0c121c, 0x152238);
  const pants = clothMat(0x0a0e16, 0x101820);
  const shoe = clothMat(0x111820, 0x1a2838);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 24, 24), skin);
  head.position.y = 1.58;
  head.scale.set(1, 1.05, 0.95);

  const hair = new THREE.Mesh(
    new THREE.SphereGeometry(0.21, 20, 20),
    clothMat(0x05080e, 0x101820)
  );
  hair.position.set(0, 1.66, -0.02);
  hair.scale.set(1.05, 0.7, 1.1);

  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.09, 0.14, 12), skin);
  neck.position.y = 1.38;

  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.26, 0.48, 8, 16), jacket);
  torso.position.y = 0.98;
  const hips = new THREE.Mesh(new THREE.SphereGeometry(0.24, 16, 16), pants);
  hips.position.y = 0.62;
  hips.scale.set(1.15, 0.55, 0.9);

  const legL = new THREE.Mesh(new THREE.CapsuleGeometry(0.09, 0.42, 6, 12), pants);
  const legR = legL.clone();
  legL.position.set(-0.12, 0.32, 0);
  legR.position.set(0.12, 0.32, 0);

  const shoeL = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.1, 0.28), shoe);
  const shoeR = shoeL.clone();
  shoeL.position.set(-0.12, 0.05, 0.04);
  shoeR.position.set(0.12, 0.05, 0.04);

  const armL = new THREE.Mesh(new THREE.CapsuleGeometry(0.065, 0.38, 6, 12), jacket);
  const armR = armL.clone();
  armL.position.set(-0.38, 1.05, 0);
  armR.position.set(0.38, 1.05, 0);
  armL.rotation.z = 0.28;
  armR.rotation.z = -0.28;

  // Наушники (потемкин) — по умолчанию скрыты
  const phones = new THREE.Group();
  const cupMat = new THREE.MeshStandardMaterial({
    color: 0x111418,
    metalness: 0.65,
    roughness: 0.35,
    emissive: 0x1a3048,
    emissiveIntensity: 0.4,
  });
  const band = new THREE.Mesh(
    new THREE.TorusGeometry(0.22, 0.025, 10, 28, Math.PI),
    cupMat
  );
  band.rotation.z = Math.PI;
  band.position.set(0, 1.7, 0);
  const cupL = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.1, 0.08, 16), cupMat);
  const cupR = cupL.clone();
  cupL.rotation.z = Math.PI / 2;
  cupR.rotation.z = Math.PI / 2;
  cupL.position.set(-0.22, 1.56, 0.02);
  cupR.position.set(0.22, 1.56, 0.02);
  const glowL = new THREE.PointLight(0x4da6ff, 0, 1.5);
  const glowR = glowL.clone();
  glowL.position.copy(cupL.position);
  glowR.position.copy(cupR.position);
  phones.add(band, cupL, cupR, glowL, glowR);
  phones.visible = false;

  root.add(head, hair, neck, torso, hips, legL, legR, shoeL, shoeR, armL, armR, phones);
  root.userData = {
    head,
    torso,
    legL,
    legR,
    armL,
    armR,
    shoeL,
    shoeR,
    phones,
    phoneGlow: [glowL, glowR],
    mat: jacket,
  };
  root.position.set(0, -1.15, -2.2);
  return root;
}

/** Лиса с текстурой «шерсти», мордой и лапами */
export function createFox() {
  const root = new THREE.Group();
  const furMap = makeFurTexture();
  const fur = new THREE.MeshStandardMaterial({
    map: furMap,
    color: 0xe07038,
    emissive: 0x4a1808,
    emissiveIntensity: 0.35,
    roughness: 0.85,
  });
  const dark = new THREE.MeshStandardMaterial({
    color: 0x1a1010,
    emissive: 0x201010,
    roughness: 0.75,
  });
  const white = new THREE.MeshStandardMaterial({
    color: 0xf5ebe0,
    emissive: 0x2a2218,
    roughness: 0.7,
  });

  const chest = new THREE.Mesh(new THREE.SphereGeometry(0.2, 20, 20), white);
  chest.position.set(0.12, 0.32, 0);
  chest.scale.set(0.9, 0.75, 0.85);

  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.5, 8, 16), fur);
  body.rotation.z = Math.PI / 2;
  body.position.set(0, 0.36, 0);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 20, 20), fur);
  head.position.set(0.42, 0.5, 0);
  head.scale.set(1.05, 0.95, 0.9);

  const snout = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.2, 12), white);
  snout.rotation.z = -Math.PI / 2;
  snout.position.set(0.58, 0.42, 0);
  const nose = new THREE.Mesh(new THREE.SphereGeometry(0.035, 10, 10), dark);
  nose.position.set(0.68, 0.42, 0);

  const earL = new THREE.Mesh(new THREE.ConeGeometry(0.065, 0.2, 8), fur);
  const earR = earL.clone();
  earL.position.set(0.36, 0.72, 0.09);
  earR.position.set(0.36, 0.72, -0.09);
  const innerL = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.1, 6), white);
  const innerR = innerL.clone();
  innerL.position.set(0.37, 0.68, 0.09);
  innerR.position.set(0.37, 0.68, -0.09);

  const tail = new THREE.Mesh(new THREE.CapsuleGeometry(0.07, 0.6, 6, 12), fur);
  tail.position.set(-0.48, 0.42, 0);
  tail.rotation.z = 0.9;
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 12), white);
  tip.position.set(-0.78, 0.68, 0);

  const makeLeg = (x, z) => {
    const g = new THREE.Group();
    const upper = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.16, 4, 8), fur);
    upper.position.y = 0.16;
    const paw = new THREE.Mesh(new THREE.SphereGeometry(0.045, 10, 10), dark);
    paw.position.set(0.02, 0.02, 0);
    paw.scale.set(1.3, 0.6, 1);
    g.add(upper, paw);
    g.position.set(x, 0.02, z);
    return g;
  };
  const legFL = makeLeg(0.22, 0.11);
  const legFR = makeLeg(0.22, -0.11);
  const legBL = makeLeg(-0.2, 0.11);
  const legBR = makeLeg(-0.2, -0.11);

  const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.03, 10, 10), dark);
  const eyeR = eyeL.clone();
  eyeL.position.set(0.52, 0.54, 0.09);
  eyeR.position.set(0.52, 0.54, -0.09);

  root.add(
    body,
    chest,
    head,
    snout,
    nose,
    earL,
    earR,
    innerL,
    innerR,
    tail,
    tip,
    legFL,
    legFR,
    legBL,
    legBR,
    eyeL,
    eyeR
  );
  root.userData = {
    body,
    head,
    tail,
    legFL,
    legFR,
    legBL,
    legBR,
    fur,
  };
  root.visible = false;
  root.position.set(2.2, -1.15, -4.5);
  root.rotation.y = -0.55;
  return root;
}

export function createPartyLights() {
  const g = new THREE.Group();
  const colors = [0xff4d3a, 0x9ec7ff, 0xffd27a, 0x7dffb3];
  const lights = colors.map((c, i) => {
    const l = new THREE.PointLight(c, 0, 14);
    l.position.set(Math.cos((i / 4) * Math.PI * 2) * 3.2, 2.4, Math.sin((i / 4) * Math.PI * 2) * 2 - 2);
    g.add(l);
    return l;
  });
  g.userData = { lights };
  return g;
}

/** Полная клавиатура сверху — для «стуком пробела» */
function createKeyboard() {
  const root = new THREE.Group();
  const board = new THREE.Mesh(
    new THREE.BoxGeometry(5.2, 0.18, 2.0),
    new THREE.MeshStandardMaterial({
      color: 0x1a1e24,
      metalness: 0.35,
      roughness: 0.45,
      emissive: 0x0a1020,
      emissiveIntensity: 0.4,
    })
  );
  board.position.y = -0.05;
  root.add(board);

  const keyMat = new THREE.MeshStandardMaterial({
    color: 0x2a3038,
    roughness: 0.55,
    metalness: 0.15,
    emissive: 0x121820,
  });
  const keys = [];
  const rows = [14, 14, 13, 12];
  let zi = 0;
  for (const count of rows) {
    for (let i = 0; i < count; i++) {
      const w = 0.28;
      const key = new THREE.Mesh(new THREE.BoxGeometry(w, 0.1, 0.28), keyMat.clone());
      key.position.set(-2.2 + i * 0.34 + (zi % 2) * 0.08, 0.08, 0.55 - zi * 0.34);
      root.add(key);
      keys.push(key);
    }
    zi += 1;
  }

  const space = new THREE.Mesh(
    new THREE.BoxGeometry(2.4, 0.14, 0.42),
    new THREE.MeshStandardMaterial({
      color: 0x3a4a60,
      emissive: 0x4a90ff,
      emissiveIntensity: 0.85,
      metalness: 0.25,
      roughness: 0.4,
    })
  );
  space.position.set(0, 0.1, -0.55);
  root.add(space);

  const finger = new THREE.Mesh(
    new THREE.SphereGeometry(0.16, 16, 16),
    skinMat(0x3a4558)
  );
  finger.scale.set(1.1, 0.55, 1.4);
  finger.position.set(0, 0.45, -0.55);
  root.add(finger);

  const desk = new THREE.Mesh(
    new THREE.PlaneGeometry(10, 7),
    new THREE.MeshStandardMaterial({
      map: makeNoiseTexture({ size: 256, base: [40, 28, 18], variance: 12 }),
      color: 0x3a2818,
      roughness: 0.9,
    })
  );
  desk.rotation.x = -Math.PI / 2;
  desk.position.y = -0.15;
  root.add(desk);

  const lamp = new THREE.PointLight(0xffe0b0, 1.6, 10);
  lamp.position.set(0, 2.2, 0.5);
  root.add(lamp);

  root.visible = false;
  root.userData = { space, finger, keys, lamp };
  return root;
}

/** Чёрный «фото» / пустой кадр — «ничего не осталось» */
function createBlackPhoto() {
  const root = new THREE.Group();
  const frame = new THREE.Mesh(
    new THREE.BoxGeometry(3.6, 2.6, 0.12),
    new THREE.MeshStandardMaterial({
      color: 0x111111,
      metalness: 0.4,
      roughness: 0.5,
      emissive: 0x222222,
    })
  );
  const photo = new THREE.Mesh(
    new THREE.PlaneGeometry(3.2, 2.2),
    new THREE.MeshBasicMaterial({ color: 0x000000 })
  );
  photo.position.z = 0.07;
  const glare = new THREE.Mesh(
    new THREE.PlaneGeometry(0.8, 2.0),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.04 })
  );
  glare.position.set(-0.9, 0.1, 0.08);
  glare.rotation.z = 0.15;
  root.add(frame, photo, glare);
  root.position.set(0, 0.6, -3.5);
  root.visible = false;
  root.userData = { photo, frame };
  return root;
}

/**
 * Реквизит под куплеты.
 */
export function createProps() {
  const props = new THREE.Group();
  const asphaltMap = makeAsphaltTexture();
  const grassMap = makeGrassTexture();
  const concreteMap = makeConcreteTexture();

  const suitcase = new THREE.Mesh(
    new THREE.BoxGeometry(0.6, 0.4, 0.32),
    new THREE.MeshStandardMaterial({
      color: 0x1a2433,
      emissive: 0x0a1525,
      roughness: 0.65,
      metalness: 0.15,
    })
  );
  suitcase.position.set(1.4, -1.0, -1.5);
  const handle = new THREE.Mesh(
    new THREE.TorusGeometry(0.12, 0.02, 8, 16, Math.PI),
    new THREE.MeshStandardMaterial({ color: 0x8899aa, metalness: 0.7, roughness: 0.3 })
  );
  handle.position.set(0, 0.28, 0);
  handle.rotation.x = Math.PI;
  suitcase.add(handle);
  suitcase.visible = false;

  const lifebuoy = new THREE.Mesh(
    new THREE.TorusGeometry(0.55, 0.12, 14, 32),
    new THREE.MeshStandardMaterial({
      color: 0xff4d3a,
      emissive: 0x66180f,
      roughness: 0.4,
      metalness: 0.25,
    })
  );
  lifebuoy.position.set(0.2, 0.2, -1.2);
  lifebuoy.rotation.x = Math.PI / 2.4;
  lifebuoy.visible = false;

  const fox = createFox();

  const road = new THREE.Group();
  const asphalt = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 48),
    new THREE.MeshStandardMaterial({
      map: asphaltMap,
      color: 0x888888,
      roughness: 0.95,
      metalness: 0.05,
    })
  );
  asphalt.rotation.x = -Math.PI / 2;
  asphalt.position.set(0, -1.28, -10);

  const shoulder = new THREE.Mesh(
    new THREE.PlaneGeometry(5.5, 48),
    new THREE.MeshStandardMaterial({
      map: grassMap,
      color: 0x889966,
      roughness: 1,
    })
  );
  shoulder.rotation.x = -Math.PI / 2;
  shoulder.position.set(3.9, -1.265, -10);

  const curb = new THREE.Mesh(
    new THREE.BoxGeometry(0.25, 0.18, 48),
    new THREE.MeshStandardMaterial({ map: concreteMap, color: 0x999999, roughness: 0.85 })
  );
  curb.position.set(2.55, -1.2, -10);

  const dashes = new THREE.Group();
  for (let i = 0; i < 16; i++) {
    const d = new THREE.Mesh(
      new THREE.PlaneGeometry(0.14, 1.05),
      new THREE.MeshBasicMaterial({ color: 0xffe08a })
    );
    d.rotation.x = -Math.PI / 2;
    d.position.set(0, -1.26, -1 - i * 2.5);
    dashes.add(d);
  }

  const rail = new THREE.Mesh(
    new THREE.BoxGeometry(0.1, 0.5, 40),
    new THREE.MeshStandardMaterial({ color: 0x8a9aaa, metalness: 0.55, roughness: 0.4 })
  );
  rail.position.set(5.6, -0.95, -10);

  const lampLights = [];
  for (let i = 0; i < 6; i++) {
    const z = -1 - i * 5.2;
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.05, 0.07, 3.4, 10),
      new THREE.MeshStandardMaterial({ color: 0x2c3038, metalness: 0.5, roughness: 0.45 })
    );
    pole.position.set(5.2, 0.4, z);
    const hood = new THREE.Mesh(
      new THREE.BoxGeometry(0.45, 0.1, 0.25),
      new THREE.MeshStandardMaterial({
        color: 0x1a1c20,
        emissive: 0xffc070,
        emissiveIntensity: 0.55,
      })
    );
    hood.position.set(4.95, 2.05, z);
    const glow = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xffd090, transparent: true, opacity: 0.55 })
    );
    glow.position.set(4.75, 1.95, z);
    const bulb = new THREE.PointLight(0xffc070, 0, 16);
    bulb.position.set(4.7, 1.9, z);
    road.add(pole, hood, glow, bulb);
    lampLights.push(bulb);
  }
  road.add(asphalt, shoulder, curb, dashes, rail);
  road.visible = false;

  const hotel = new THREE.Group();
  const wallMat = new THREE.MeshStandardMaterial({
    map: concreteMap,
    color: 0xbb9988,
    emissive: 0x3a1810,
    emissiveIntensity: 0.3,
    roughness: 0.9,
  });
  const floorMat = new THREE.MeshStandardMaterial({
    color: 0x1a1410,
    emissive: 0x2a1810,
    emissiveIntensity: 0.2,
    roughness: 0.95,
  });
  const back = new THREE.Mesh(new THREE.PlaneGeometry(10, 6), wallMat);
  back.position.set(0, 1.2, -7);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(10, 8), floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(0, -1.2, -3.5);
  const sideL = new THREE.Mesh(new THREE.PlaneGeometry(8, 6), wallMat);
  sideL.rotation.y = Math.PI / 2;
  sideL.position.set(-4.5, 1.2, -4);
  const sideR = sideL.clone();
  sideR.position.x = 4.5;
  sideR.rotation.y = -Math.PI / 2;
  const bed = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 0.4, 1.5),
    new THREE.MeshStandardMaterial({ color: 0x5a3a30, emissive: 0x2a1510, roughness: 0.85 })
  );
  bed.position.set(-1.1, -0.9, -4.0);
  const pillow = new THREE.Mesh(
    new THREE.BoxGeometry(0.7, 0.18, 0.45),
    new THREE.MeshStandardMaterial({ color: 0xc8b8a0, emissive: 0x3a3020 })
  );
  pillow.position.set(-1.7, -0.62, -4.35);
  const neon = new THREE.Mesh(
    new THREE.BoxGeometry(2.8, 0.55, 0.1),
    new THREE.MeshStandardMaterial({
      color: 0xff4d6a,
      emissive: 0xff2a55,
      emissiveIntensity: 2.2,
    })
  );
  neon.position.set(0.2, 2.2, -6.7);
  const neonLight = new THREE.PointLight(0xff4d6a, 0, 14);
  neonLight.position.set(0.2, 1.8, -4.8);
  const windowGlow = new THREE.Mesh(
    new THREE.PlaneGeometry(1.8, 2.2),
    new THREE.MeshBasicMaterial({ color: 0xffd27a, transparent: true, opacity: 0.55 })
  );
  windowGlow.position.set(2.9, 1.2, -6.85);
  for (let i = 0; i < 5; i++) {
    const c = new THREE.Mesh(
      new THREE.PlaneGeometry(0.28, 2.1),
      new THREE.MeshStandardMaterial({
        color: 0x6a3040,
        emissive: 0x3a1020,
        transparent: true,
        opacity: 0.7,
      })
    );
    c.position.set(2.3 + i * 0.28, 1.15, -6.8);
    hotel.add(c);
  }
  hotel.add(back, floor, sideL, sideR, bed, pillow, neon, neonLight, windowGlow);
  hotel.visible = false;
  hotel.userData = { neonLight, neon };

  const fountain = new THREE.Group();
  const box = new THREE.Mesh(
    new THREE.BoxGeometry(0.85, 0.65, 0.85),
    new THREE.MeshStandardMaterial({ color: 0xd0b898, emissive: 0x4a3820, roughness: 0.55 })
  );
  box.position.set(0, -0.95, -3.0);
  const lid = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.08, 0.5),
    new THREE.MeshStandardMaterial({ color: 0xb89870, emissive: 0x3a2810 })
  );
  lid.position.set(0.35, -0.55, -3.0);
  lid.rotation.z = -0.7;
  const jets = [];
  const spray = new THREE.PointLight(0x7ec8ff, 0, 8);
  spray.position.set(0, 1.2, -3.0);
  for (let i = 0; i < 9; i++) {
    const jet = new THREE.Mesh(
      new THREE.CylinderGeometry(0.04, 0.08, 2.2, 8),
      new THREE.MeshStandardMaterial({
        color: 0x9ee0ff,
        emissive: 0x3a90cc,
        emissiveIntensity: 1.2,
        transparent: true,
        opacity: 0.85,
      })
    );
    const ang = (i / 9) * Math.PI * 2;
    jet.position.set(Math.cos(ang) * 0.12, 0.2, -3.0 + Math.sin(ang) * 0.12);
    jets.push(jet);
    fountain.add(jet);
  }
  fountain.add(box, lid, spray);
  fountain.visible = false;
  fountain.userData = { jets, box, spray };

  const metro = new THREE.Group();
  for (let i = 0; i < 8; i++) {
    const pillar = new THREE.Mesh(
      new THREE.BoxGeometry(0.55, 3.6, 0.55),
      new THREE.MeshStandardMaterial({
        map: concreteMap,
        color: 0x8899aa,
        emissive: 0x101820,
        roughness: 0.7,
      })
    );
    pillar.position.set(i % 2 === 0 ? -2.4 : 2.4, 0.5, -1 - i * 2.2);
    metro.add(pillar);
  }
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(2.4, 0.55),
    new THREE.MeshBasicMaterial({ color: 0xff4d3a })
  );
  sign.position.set(0, 2.2, -6);
  const tiles = new THREE.Mesh(
    new THREE.PlaneGeometry(12, 40),
    new THREE.MeshStandardMaterial({ color: 0x1a222c, roughness: 0.6, metalness: 0.2 })
  );
  tiles.rotation.x = -Math.PI / 2;
  tiles.position.set(0, -1.25, -8);
  metro.add(sign, tiles);
  metro.visible = false;

  const scrub = createKeyboard();
  const blackPhoto = createBlackPhoto();

  const hands = new THREE.Group();
  const handMat = skinMat(0x2a3448);
  const handL = new THREE.Mesh(new THREE.SphereGeometry(0.18, 16, 16), handMat);
  const handR = handL.clone();
  handL.scale.set(1.2, 0.55, 1.6);
  handR.scale.set(1.2, 0.55, 1.6);
  handL.position.set(-0.55, 0.3, -1.4);
  handR.position.set(0.55, 0.25, -1.5);
  hands.add(handL, handR);
  hands.visible = false;
  hands.userData = { handL, handR };

  const home = new THREE.Group();
  const facade = new THREE.Mesh(
    new THREE.PlaneGeometry(7, 5),
    new THREE.MeshStandardMaterial({
      map: concreteMap,
      color: 0x667788,
      emissive: 0x0a1525,
      roughness: 0.9,
    })
  );
  facade.position.set(0, 1.0, -8);
  const win = new THREE.Mesh(
    new THREE.PlaneGeometry(1.4, 1.6),
    new THREE.MeshBasicMaterial({ color: 0xffd27a, transparent: true, opacity: 0.55 })
  );
  win.position.set(-1.2, 1.3, -7.95);
  const win2 = win.clone();
  win2.position.x = 1.1;
  win2.material = win.material.clone();
  win2.material.opacity = 0.18;
  home.add(facade, win, win2);
  home.visible = false;
  home.userData = { win, win2 };

  const foxGlow = new THREE.PointLight(0xff7a3a, 0, 10);
  foxGlow.position.set(2.0, 0.6, -4.0);

  props.add(
    suitcase,
    lifebuoy,
    fox,
    road,
    hotel,
    fountain,
    metro,
    scrub,
    blackPhoto,
    hands,
    home,
    foxGlow
  );
  props.userData = {
    suitcase,
    lifebuoy,
    fox,
    road,
    hotel,
    fountain,
    metro,
    scrub,
    blackPhoto,
    hands,
    home,
    foxGlow,
    lampLights,
  };
  return props;
}
