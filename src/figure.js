import * as THREE from 'three';

const matDark = () =>
  new THREE.MeshStandardMaterial({
    color: 0x02040a,
    emissive: 0x1a2a44,
    emissiveIntensity: 0.55,
    roughness: 0.85,
    metalness: 0.08,
  });

/** Простой силуэт человека */
export function createFigure() {
  const root = new THREE.Group();
  const mat = matDark();

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16), mat);
  head.position.y = 1.55;
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.55, 6, 12), mat);
  torso.position.y = 0.95;
  const legL = new THREE.Mesh(new THREE.CapsuleGeometry(0.1, 0.45, 4, 8), mat);
  const legR = legL.clone();
  legL.position.set(-0.12, 0.35, 0);
  legR.position.set(0.12, 0.35, 0);
  const armL = new THREE.Mesh(new THREE.CapsuleGeometry(0.07, 0.4, 4, 8), mat);
  const armR = armL.clone();
  armL.position.set(-0.4, 1.05, 0);
  armR.position.set(0.4, 1.05, 0);
  armL.rotation.z = 0.25;
  armR.rotation.z = -0.25;

  root.add(head, torso, legL, legR, armL, armR);
  root.userData = { head, torso, legL, legR, armL, armR, mat };
  root.position.set(0, -1.15, -2.2);
  return root;
}

/** Стилизованная лиса — тело / голова / хвост / уши */
export function createFox() {
  const root = new THREE.Group();
  const fur = new THREE.MeshStandardMaterial({
    color: 0xc45a28,
    emissive: 0x5a2208,
    emissiveIntensity: 0.45,
    roughness: 0.7,
  });
  const dark = new THREE.MeshStandardMaterial({
    color: 0x1a1010,
    emissive: 0x2a1010,
    roughness: 0.8,
  });
  const white = new THREE.MeshStandardMaterial({
    color: 0xf0e6d8,
    emissive: 0x332820,
    roughness: 0.75,
  });

  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 0.55, 6, 12), fur);
  body.rotation.z = Math.PI / 2;
  body.position.set(0, 0.35, 0);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 14, 14), fur);
  head.position.set(0.42, 0.48, 0);
  head.scale.set(1, 0.95, 0.85);

  const snout = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.22, 8), white);
  snout.rotation.z = -Math.PI / 2;
  snout.position.set(0.58, 0.4, 0);

  const earL = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.18, 6), fur);
  const earR = earL.clone();
  earL.position.set(0.38, 0.7, 0.1);
  earR.position.set(0.38, 0.7, -0.1);

  const tail = new THREE.Mesh(new THREE.CapsuleGeometry(0.08, 0.55, 4, 8), fur);
  tail.position.set(-0.45, 0.4, 0);
  tail.rotation.z = 0.85;
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.09, 10, 10), white);
  tip.position.set(-0.72, 0.62, 0);

  const legFL = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.22, 3, 6), dark);
  const legFR = legFL.clone();
  const legBL = legFL.clone();
  const legBR = legFL.clone();
  legFL.position.set(0.22, 0.12, 0.12);
  legFR.position.set(0.22, 0.12, -0.12);
  legBL.position.set(-0.18, 0.12, 0.12);
  legBR.position.set(-0.18, 0.12, -0.12);

  const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.035, 8, 8), dark);
  const eyeR = eyeL.clone();
  eyeL.position.set(0.52, 0.52, 0.1);
  eyeR.position.set(0.52, 0.52, -0.1);

  root.add(body, head, snout, earL, earR, tail, tip, legFL, legFR, legBL, legBR, eyeL, eyeR);
  root.userData = { body, head, tail, legFL, legFR, legBL, legBR, fur };
  root.visible = false;
  root.position.set(2.2, -1.15, -4.5);
  root.rotation.y = -0.55;
  return root;
}

export function createPartyLights() {
  const g = new THREE.Group();
  const colors = [0xff4d3a, 0x9ec7ff, 0xffd27a, 0x7dffb3];
  const lights = colors.map((c, i) => {
    const l = new THREE.PointLight(c, 0, 12);
    l.position.set(Math.cos((i / 4) * Math.PI * 2) * 3, 2.2, Math.sin((i / 4) * Math.PI * 2) * 2 - 2);
    g.add(l);
    return l;
  });
  g.userData = { lights };
  return g;
}

/**
 * Реквизит под куплеты: дорога, лиса, отель, фонтан, метро, руки, пробел, дом.
 */
export function createProps() {
  const props = new THREE.Group();

  const suitcase = new THREE.Mesh(
    new THREE.BoxGeometry(0.55, 0.38, 0.28),
    new THREE.MeshStandardMaterial({ color: 0x1a2433, emissive: 0x0a1525, roughness: 0.7 })
  );
  suitcase.position.set(1.4, -1.0, -1.5);
  suitcase.visible = false;

  const lifebuoy = new THREE.Mesh(
    new THREE.TorusGeometry(0.55, 0.12, 12, 28),
    new THREE.MeshStandardMaterial({
      color: 0xff4d3a,
      emissive: 0x66180f,
      roughness: 0.45,
      metalness: 0.2,
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
      color: 0x10141a,
      emissive: 0x06080c,
      roughness: 0.95,
    })
  );
  asphalt.rotation.x = -Math.PI / 2;
  asphalt.position.set(0, -1.28, -10);

  const shoulder = new THREE.Mesh(
    new THREE.PlaneGeometry(5, 48),
    new THREE.MeshStandardMaterial({ color: 0x2a2216, emissive: 0x151008, roughness: 1 })
  );
  shoulder.rotation.x = -Math.PI / 2;
  shoulder.position.set(3.8, -1.265, -10);

  const dashes = new THREE.Group();
  for (let i = 0; i < 16; i++) {
    const d = new THREE.Mesh(
      new THREE.PlaneGeometry(0.16, 1.05),
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
      new THREE.CylinderGeometry(0.05, 0.07, 3.4, 8),
      new THREE.MeshStandardMaterial({ color: 0x2c3038 })
    );
    pole.position.set(5.2, 0.4, z);
    const hood = new THREE.Mesh(
      new THREE.BoxGeometry(0.4, 0.08, 0.22),
      new THREE.MeshStandardMaterial({
        color: 0x1a1c20,
        emissive: 0xffc070,
        emissiveIntensity: 0.35,
      })
    );
    hood.position.set(4.95, 2.05, z);
    const bulb = new THREE.PointLight(0xffc070, 0, 16);
    bulb.position.set(4.7, 1.9, z);
    road.add(pole, hood, bulb);
    lampLights.push(bulb);
  }
  road.add(asphalt, shoulder, dashes, rail);
  road.visible = false;

  const hotel = new THREE.Group();
  const wallMat = new THREE.MeshStandardMaterial({
    color: 0x3a281c,
    emissive: 0x4a2018,
    emissiveIntensity: 0.35,
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
  // cheap curtain strips
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
      new THREE.MeshStandardMaterial({ color: 0x2a3340, emissive: 0x101820, roughness: 0.7 })
    );
    pillar.position.set(i % 2 === 0 ? -2.4 : 2.4, 0.5, -1 - i * 2.2);
    metro.add(pillar);
  }
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(2.4, 0.55),
    new THREE.MeshBasicMaterial({ color: 0xff4d3a })
  );
  sign.position.set(0, 2.2, -6);
  metro.add(sign);
  metro.visible = false;

  const scrub = new THREE.Group();
  const bar = new THREE.Mesh(
    new THREE.BoxGeometry(3.2, 0.35, 0.7),
    new THREE.MeshStandardMaterial({
      color: 0x1a2230,
      emissive: 0x3a6aa0,
      emissiveIntensity: 0.5,
      metalness: 0.3,
      roughness: 0.4,
    })
  );
  bar.position.set(0, -0.2, -2.5);
  const caret = new THREE.Mesh(
    new THREE.BoxGeometry(0.12, 0.55, 0.12),
    new THREE.MeshBasicMaterial({ color: 0x9ec7ff })
  );
  caret.position.set(-1.2, 0.2, -2.5);
  scrub.add(bar, caret);
  scrub.visible = false;
  scrub.userData = { bar, caret };

  const hands = new THREE.Group();
  const handMat = matDark();
  const handL = new THREE.Mesh(new THREE.SphereGeometry(0.18, 12, 12), handMat);
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
    new THREE.MeshStandardMaterial({ color: 0x152030, emissive: 0x0a1525, roughness: 0.9 })
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

  props.add(suitcase, lifebuoy, fox, road, hotel, fountain, metro, scrub, hands, home, foxGlow);
  props.userData = {
    suitcase,
    lifebuoy,
    fox,
    road,
    hotel,
    fountain,
    metro,
    scrub,
    hands,
    home,
    foxGlow,
    lampLights,
  };
  return props;
}
