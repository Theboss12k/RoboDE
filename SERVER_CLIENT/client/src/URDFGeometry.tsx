import { useEffect,useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Model } from "./types";
import { disposeModel } from "./modelAssets";
type Geometry=NonNullable<Model["geometry"]>[number];
function MeshAsset({model,entry,collision}:{model:Model;entry:Geometry;collision:boolean}){
 const [scene,setScene]=useState<THREE.Object3D|null>(null),[error,setError]=useState(false);
 useEffect(()=>{let active=true,loaded:THREE.Object3D|null=null;const controller=new AbortController();setScene(null);setError(false);
  const asset=(entry as Geometry&{asset?:{sha256?:string;path?:string}}).asset;
  if(!asset?.sha256){setError(true);return}
  void (async()=>{const response=await fetch(`/api/registry/${encodeURIComponent(model.robot.id)}/source/assets/${asset.sha256}`,{signal:controller.signal});if(!response.ok)throw Error("Mesh missing");const bytes=await response.arrayBuffer();if(bytes.byteLength>25*1024*1024)throw Error("Mesh too large");const suffix=asset.path?.split(".").at(-1)?.toLowerCase();
   if(suffix==="stl")loaded=new THREE.Mesh(new STLLoader().parse(bytes));else if(suffix==="obj")loaded=new OBJLoader().parse(new TextDecoder().decode(bytes));else if(suffix==="glb"||suffix==="gltf"){
    const manager=new THREE.LoadingManager();manager.setURLModifier(url=>{if(!url.startsWith("data:")&&!url.startsWith("blob:"))throw Error("External mesh resources are unavailable");return url});loaded=(await new GLTFLoader(manager).parseAsync(bytes,"")).scene;
   }else throw Error("Mesh format unsupported in built-in view");
   loaded.traverse(n=>{const mesh=n as THREE.Mesh;if(mesh.isMesh){const old=Array.isArray(mesh.material)?mesh.material:[mesh.material];old.forEach(m=>m?.dispose());mesh.material=new THREE.MeshStandardMaterial({color:collision?"#edb75a":"#a5b8cc",wireframe:collision,transparent:collision,opacity:collision?.3:1,roughness:.5});mesh.castShadow=!collision;mesh.receiveShadow=!collision}});if(active)setScene(loaded);else disposeModel(loaded);
  })().catch(()=>{if(active)setError(true)});
  return()=>{active=false;controller.abort();if(loaded)disposeModel(loaded)};
 },[model.robot.id,entry,collision]);
 if(error)return <mesh><boxGeometry args={[.04,.04,.04]}/><meshBasicMaterial color="#f9be53" wireframe/></mesh>;
 return scene?<primitive object={scene}/>:null;
}
export default function URDFGeometry({model,frames,onSelect,selected}:{model:Model;frames:Record<string,THREE.Matrix4>;onSelect?:(id:string)=>void;selected?:string}){
 const [collision,setCollision]=useState(false);
 // The parent view exposes this event from its geometry toggle.
 useEffect(()=>{const listener=(event:Event)=>setCollision((event as CustomEvent<boolean>).detail);window.addEventListener("robode:collision-geometry",listener);return()=>window.removeEventListener("robode:collision-geometry",listener)},[]);
 const basis=new THREE.Matrix4().makeRotationX(-Math.PI/2);
 return <group>{model.geometry?.filter(g=>g.kind==="visual"||collision).map((g,i)=>{if(!frames[g.link])return null;
  const origin=new THREE.Matrix4().compose(new THREE.Vector3(...g.origin.xyz as [number,number,number]),new THREE.Quaternion().setFromEuler(new THREE.Euler(...g.origin.rpy as [number,number,number],"ZYX")),new THREE.Vector3(1,1,1));
  const transform=basis.clone().multiply(frames[g.link]).multiply(origin),p=g.parameters,isCollision=g.kind==="collision",part="link:"+g.link;
  const scale=(p.scale as [number,number,number])??[1,1,1];const child=model.kinematics.joints?.find(j=>j.child===g.link);
  return <group key={i} matrixAutoUpdate={false} matrix={transform} onClick={e=>{e.stopPropagation();onSelect?.(part)}}>
   {g.shape==="mesh"?<group scale={scale}><MeshAsset model={model} entry={g} collision={isCollision}/></group>:<mesh rotation={g.shape==="cylinder"?[Math.PI/2,0,0]:[0,0,0]}><>{g.shape==="box"?<boxGeometry args={p.size as [number,number,number]}/>:g.shape==="sphere"?<sphereGeometry args={[Number(p.radius),24,24]}/>:<cylinderGeometry args={[Number(p.radius),Number(p.radius),Number(p.length),24]}/>}</><meshStandardMaterial color={selected===part||selected===`actuator:${child?.actuator}`?"#72adff":isCollision?"#e4a64d":"#a7b7c9"} wireframe={isCollision} transparent={isCollision} opacity={isCollision?.3:1} metalness={.3} roughness={.5}/></mesh>}
  </group>})}</group>
}
