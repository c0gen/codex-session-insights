import {
  BoxGeometry,
  InstancedMesh,
  InstancedBufferAttribute,
  MeshStandardMaterial,
  ShaderMaterial,
  Matrix4,
  Quaternion,
  Vector3,
  type Group,
} from "three";

export interface Solid {
  x: number;
  y: number;
  z: number;
  w: number;
  h: number;
  d: number;
  rotation?: number;
  items?: number;
}
export function solids(
  root: Group,
  items: Solid[],
  color: number,
  pattern?: "spines" | "sections",
) {
  if (!items.length) return;
  const geometry = new BoxGeometry(1, 1, 1);
  let material: MeshStandardMaterial | ShaderMaterial;
  if (pattern === "sections") {
    material = new ShaderMaterial({
      vertexShader: `varying vec3 positionWorld; void main(){vec4 p=modelMatrix*instanceMatrix*vec4(position,1.0);positionWorld=p.xyz;gl_Position=projectionMatrix*viewMatrix*p;}`,
      fragmentShader: `varying vec3 positionWorld; void main(){float x=mod(positionWorld.x+.66,12.0);float z=mod(positionWorld.z+.31,8.6);float bay=mod(x,1.38);float row=mod(z,1.85);if(x>10.98||z>6.17||bay>1.32||row>.62||(row>.30&&row<.32))discard;float edge=min(min(bay,1.32-bay),min(row,.62-row));vec3 col=mix(vec3(.35,.29,.2),vec3(.65,.53,.35),smoothstep(0.0,.06,edge));gl_FragColor=vec4(col,1.0);}`,
    });
  } else if (pattern === "spines") {
    geometry.setAttribute(
      "items",
      new InstancedBufferAttribute(
        new Float32Array(items.map((i) => i.items ?? 1)),
        1,
      ),
    );
    material = new ShaderMaterial({
      vertexShader: `attribute float items; varying vec2 uvSpine; varying float count; void main(){uvSpine=uv;count=items;gl_Position=projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0);}`,
      fragmentShader: `varying vec2 uvSpine; varying float count; void main(){float slot=floor(uvSpine.x*count);float edge=step(.07,fract(uvSpine.x*count));float choice=mod(slot,3.0);vec3 col=choice<1.0?vec3(.27,.46,.5):choice<2.0?vec3(.62,.35,.27):vec3(.4,.49,.31);float gold=step(.025,abs(uvSpine.y-.17))*step(.025,abs(uvSpine.y-.82));col=mix(vec3(.79,.66,.43),col,gold);gl_FragColor=vec4(col*mix(.48,1.0,edge),1.0);}`,
    });
  } else material = new MeshStandardMaterial({ color, roughness: 0.85 });
  const mesh = new InstancedMesh(geometry, material, items.length),
    q = new Quaternion();
  items.forEach((s, i) =>
    mesh.setMatrixAt(
      i,
      new Matrix4().compose(
        new Vector3(s.x, s.y, s.z),
        q.setFromAxisAngle(new Vector3(0, 1, 0), s.rotation ?? 0),
        new Vector3(s.w, s.h, s.d),
      ),
    ),
  );
  mesh.computeBoundingSphere();
  root.add(mesh);
}
