import * as THREE from 'three';

/** Простой силуэт человека + реквизит для сюжетных сцен */
export function createFigure() {
  const root = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: 0x02040a,
    emissive: 0x1a2a44,
    emissiveIntensity: 0.55,
    roughness: 0.85,
    metalness: 0.08,
  });

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

  const foxGlow = new THREE.PointLight(0xff7a3a, 0, 8);
  foxGlow.position.set(0, 1.2, 0);

  props.add(suitcase, lifebuoy, foxGlow);
  props.userData = { suitcase, lifebuoy, foxGlow };
  return props;
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
