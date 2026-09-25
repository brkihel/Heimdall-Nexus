using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering;
using Debug=UnityEngine.Debug;
namespace Heimdall.Sagas.Mod;
internal sealed partial class RuntimeArt {
 IEnumerator<object?>? capture;Player? capturePlayer;string captureSignature="",captureWorld="";int captureGeneration,captureSteps;float captureStarted,nextAppearanceCheck;readonly PortraitWorkTiming captureTiming=new PortraitWorkTiming();
 Task<byte[]>? probeProcessing;string capturePhase="preparation";readonly Dictionary<string,double> capturePhaseMax=new Dictionary<string,double>();
 void CaptureWork(double ms,string phase){captureTiming.Add(Time.frameCount,ms);capturePhaseMax[phase]=Math.Max(capturePhaseMax.TryGetValue(phase,out var previous)?previous:0,ms);}
 void CancelCapture(){var current=capture;capture=null;current?.Dispose();}
 public void PumpPortrait(Player? player,bool permitted,string world){
  CheckThread();if(capture==null)return;
  if(!permitted||!player||player!=capturePlayer||world!=captureWorld||generation!=captureGeneration||!Standing(player)){
   CancelCapture();refresh.Defer();Status=player&&!Standing(player)?"waiting-for-standing":"capture-cancelled";return;
  }
  if(Time.realtimeSinceStartup>=nextAppearanceCheck){nextAppearanceCheck=Time.realtimeSinceStartup+.2f;if(Appearance(player)!=captureSignature){CancelCapture();Status="appearance-changed";return;}}
  var timer=Stopwatch.StartNew();
  try{if(!capture.MoveNext()){CaptureWork(timer.Elapsed.TotalMilliseconds,capturePhase);timer.Restart();CancelCapture();Debug.Log("Sagas staged portrait: "+captureSteps+" steps, max main-thread capture work/frame="+captureTiming.Maximum.ToString("F1")+" ms, elapsed="+(Time.realtimeSinceStartup-captureStarted).ToString("F2")+" s; max step by phase: "+string.Join(", ",capturePhaseMax.Select(p=>p.Key+"="+p.Value.ToString("F1")+" ms"))+"; image processing continues in background.");}}
  catch(Exception e){CancelCapture();refresh.Failed(Time.realtimeSinceStartup);forceSimplified=true;Status="capture-failed";warn("staged portrait",e);}
  finally{captureSteps++;CaptureWork(timer.Elapsed.TotalMilliseconds,capturePhase);}
 }
 struct FrozenPose {internal Transform? Parent;internal Vector3 Position,Scale;internal Quaternion Rotation;}
 static Dictionary<Transform,FrozenPose> FreezePoses(Player player){
  var poses=new Dictionary<Transform,FrozenPose>();
  foreach(var child in player.GetComponentsInChildren<Transform>(true)){
   for(var current=child;current&&!poses.ContainsKey(current);current=current.parent){if(poses.Count>=1024)throw new InvalidOperationException("Portrait transform limit exceeded.");poses[current]=new FrozenPose{Parent=current.parent,Position=current.localPosition,Scale=current.localScale,Rotation=current.localRotation};}
  }return poses;
 }
 static Transform CopyFrozenPose(Transform source,Transform root,Dictionary<Transform,Transform> copies,Dictionary<Transform,FrozenPose> poses,int layer,int depth=0){
  if(copies.TryGetValue(source,out var known))return known;
  if(depth>=128||!poses.TryGetValue(source,out var pose))throw new InvalidOperationException("Appearance hierarchy changed during portrait preparation.");
  var parent=pose.Parent?CopyFrozenPose(pose.Parent,root,copies,poses,layer,depth+1):root;
  var node=new GameObject("Sagas frozen pose"){hideFlags=HideFlags.HideAndDontSave,layer=layer};var copy=node.transform;copy.SetParent(parent,false);copy.localPosition=pose.Position;copy.localRotation=pose.Rotation;copy.localScale=pose.Scale;copies[source]=copy;return copy;
 }
 IEnumerable<object?> BuildPortrait(Player player,string signature){
  GameObject? root=null;Cubemap? studio=null;PortraitReadbackPair? pair=null;
  var renderers=new List<Renderer>();var fallbackMaterials=new List<Material>();var effectMeshes=new List<Mesh>();var diagnostics=new System.Text.StringBuilder();
  try{
   capturePhase="scene scan";uint usedLayers=0;var existing=UnityEngine.Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None);
   for(int i=0;i<existing.Length;i++){if(existing[i])usedLayers|=1u<<existing[i].gameObject.layer;if(i%128==127)yield return null;}
   int captureLayer=30;while(captureLayer>=0&&(usedLayers&(1u<<captureLayer))!=0)captureLayer--;if(captureLayer<0)throw new InvalidOperationException("No isolated portrait layer available.");
   yield return null;
   // Recreate only transforms and visual components. Keeping native skinning
   // preserves bone matrices, bindposes and GPU vertex/index buffers; converting
   // BakeMesh into a MeshRenderer rendered static equipment but no body in the
   // observed Unity6 runtime. No Player/Animator/VisEquipment script is cloned.
   root=new GameObject("Sagas temporary portrait geometry"){hideFlags=HideFlags.HideAndDontSave};
   root.SetActive(false);UnityEngine.Object.DontDestroyOnLoad(root);
   var poses=new Dictionary<Transform,Transform>();
   capturePhase="pose snapshot";var frozen=FreezePoses(player);var frozenPosition=player.transform.position;var frozenYaw=player.transform.eulerAngles.y;
   var sources=player.GetComponentsInChildren<Renderer>();var savedBounds=sources.ToDictionary(r=>r,r=>r.bounds);
   yield return null;
   int count=0,vertices=0;Bounds bounds=new Bounds();bool hasBounds=false;
   var visual=player.GetComponentInChildren<VisEquipment>();var bodySource=visual?visual.m_bodyModel:null;
   Renderer? capturedBody=null;
   foreach(var source in sources) {
    capturePhase="renderer assembly";
    if(!source.enabled||!source.gameObject.activeInHierarchy)continue;
    Mesh? mesh=source is SkinnedMeshRenderer skinSource?skinSource.sharedMesh:source is MeshRenderer?source.GetComponent<MeshFilter>()?.sharedMesh:null;
    if(!mesh||vertices+mesh.vertexCount>250000||count>=64)continue;
    var node=CopyFrozenPose(source.transform,root.transform,poses,frozen,captureLayer).gameObject;
    Renderer renderer;
    if(source is SkinnedMeshRenderer skin){
     var copy=node.AddComponent<SkinnedMeshRenderer>();copy.enabled=false;
     var sourceBones=skin.bones;var bones=new Transform[sourceBones.Length];
     for(int i=0;i<bones.Length;i++){bones[i]=sourceBones[i]?CopyFrozenPose(sourceBones[i],root.transform,poses,frozen,captureLayer):null!;if(i%8==7)yield return null;}
     copy.sharedMesh=mesh;copy.bones=bones;
     copy.rootBone=skin.rootBone?CopyFrozenPose(skin.rootBone,root.transform,poses,frozen,captureLayer):null;
     copy.quality=skin.quality;copy.localBounds=skin.localBounds;
     copy.updateWhenOffscreen=true;copy.forceMatrixRecalculationPerRender=true;copy.skinnedMotionVectors=false;
     if(diagnostics.Length<3200){int missing=0;foreach(var bone in bones)if(!bone)missing++;diagnostics.Append("bones=").Append(bones.Length).Append(" missing=").Append(missing).Append(" root=").Append((bool)copy.rootBone).Append(';');}
     for(int i=0;i<mesh.blendShapeCount;i++)copy.SetBlendShapeWeight(i,skin.GetBlendShapeWeight(i));
     renderer=copy;
    }else{
     node.AddComponent<MeshFilter>().sharedMesh=mesh;
     renderer=node.AddComponent<MeshRenderer>();
    }
    count++;vertices+=mesh.vertexCount;
    renderer.sharedMaterials=source.sharedMaterials;renderers.Add(renderer);
    if(source==bodySource)capturedBody=renderer;
    var properties=new MaterialPropertyBlock();source.GetPropertyBlock(properties);renderer.SetPropertyBlock(properties);
    for(int slot=0;slot<source.sharedMaterials.Length;slot++){var perMaterial=new MaterialPropertyBlock();source.GetPropertyBlock(perMaterial,slot);renderer.SetPropertyBlock(perMaterial,slot);}
    PortraitLighting.IsolateProbes(renderer);
    renderer.enabled=true;renderer.forceRenderingOff=false;renderer.shadowCastingMode=UnityEngine.Rendering.ShadowCastingMode.Off;renderer.receiveShadows=false;
    // The clone retains the full original hierarchy, so live world bounds are
    // also the exact intended clone bounds. Set the clone's culling bounds
    // explicitly before its first render instead of waiting for a frame update.
    renderer.bounds=savedBounds[source];
    if(!hasBounds){bounds=savedBounds[source];hasBounds=true;}else bounds.Encapsulate(savedBounds[source]);
    if(diagnostics.Length<3500){
     uint indices=0;for(int sub=0;sub<mesh.subMeshCount;sub++)indices+=mesh.GetIndexCount(sub);
     diagnostics.Append(source.name.Length>64?source.name.Substring(0,64):source.name).Append(": v=").Append(mesh.vertexCount).Append(" indices=").Append(indices).Append(" sub=").Append(mesh.subMeshCount).Append(" center-offset=").Append(savedBounds[source].center-frozenPosition).Append(" size=").Append(savedBounds[source].size).Append(" skin=").Append(source is SkinnedMeshRenderer).Append(';');
    }
    yield return null;
   }
   yield return null;
   if(!capturedBody){Status="body-unavailable";warn("character portrait",new InvalidOperationException("Refusing partial equipment-only portrait: the player's VisEquipment body was missing or rejected. "+diagnostics));throw new EmptyPortraitException("Body/geometry unavailable.");}
   if(!hasBounds||vertices==0||bounds.size.sqrMagnitude<.001f){Status="waiting-for-geometry";warn("character portrait",new InvalidOperationException("No visible equipped geometry is ready. "+diagnostics));throw new EmptyPortraitException("Body/geometry unavailable.");}
   var cameraObject=new GameObject("Sagas temporary portrait camera"){hideFlags=HideFlags.HideAndDontSave};
   cameraObject.transform.SetParent(root.transform,false);
   var camera=cameraObject.AddComponent<Camera>();camera.enabled=false;
   camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.035f,.055f,.065f,0);
   // Inspected installed Jotunn RenderManager documents that Valheim material
   // shaders do not support orthographic capture. A narrow perspective keeps
   // this static2D portrait visually flat without that incompatible projection.
   camera.cullingMask=1<<captureLayer;camera.orthographic=false;camera.fieldOfView=Mathf.Clamp(Style.FieldOfView,6,40);camera.aspect=2f/3f;
   var aim=bounds.center;
   float distance=PortraitGeometry.RotatingCameraDistance(bounds.extents.x,bounds.extents.y,bounds.extents.z,camera.aspect,camera.fieldOfView);
   var facing=Quaternion.Euler(0,frozenYaw,0);
   camera.transform.position=aim+facing*new Vector3(Mathf.Clamp(Style.SideAngle,-1,1),0,1).normalized*distance;
   camera.transform.LookAt(aim);camera.nearClipPlane=.05f;camera.farClipPlane=distance+bounds.size.magnitude+10;
   camera.allowHDR=false;camera.allowMSAA=false;camera.useOcclusionCulling=false;camera.renderingPath=RenderingPath.Forward;camera.layerCullDistances=new float[32];camera.layerCullSpherical=false;
   var lampObject=new GameObject("Sagas temporary portrait light"){hideFlags=HideFlags.HideAndDontSave};
   lampObject.transform.SetParent(root.transform,false);
   var lamp=lampObject.AddComponent<Light>();lamp.type=LightType.Directional;lamp.cullingMask=1<<captureLayer;
   lamp.intensity=Mathf.Clamp(Style.Key,0,3);lamp.color=Color.white;lamp.shadows=LightShadows.None;lamp.renderMode=LightRenderMode.ForcePixel;
   lamp.transform.rotation=Quaternion.LookRotation(facing*new Vector3(.35f,-.35f,-1));
   var fillObject=new GameObject("Sagas temporary portrait fill"){hideFlags=HideFlags.HideAndDontSave};
   fillObject.transform.SetParent(root.transform,false);
   var fill=fillObject.AddComponent<Light>();fill.type=LightType.Directional;fill.cullingMask=1<<captureLayer;
   fill.intensity=Mathf.Clamp(Style.Fill,0,3);fill.color=Color.white;fill.shadows=LightShadows.None;fill.renderMode=LightRenderMode.ForcePixel;
   fill.transform.rotation=Quaternion.LookRotation(facing*new Vector3(-.5f,0,-1));
   capturePhase="lighting and effects";int equippedRendererCount=renderers.Count;
   foreach(var step in CaptureEffects(player,root,camera,captureLayer,bounds,renderers,effectMeshes,diagnostics,frozen,poses,frozenPosition))yield return step;

   yield return null;
   capturePhase="studio reflection";studio=PortraitLighting.CreateStudioReflection();yield return null;
   bool simplified=forceSimplified&&UseFallback(renderers,fallbackMaterials,equippedRendererCount);
   // Two passes per stage in the SAME frame keep shader time/effects identical. No scene state survives a yield.
   for(int stage=0;stage<4;stage++){
    int width=stage==3?1024:341;
    foreach(var renderer in renderers)renderer.enabled=(stage==0||stage==2)?renderer==capturedBody:true;
    yield return null;
    capturePhase="render pass "+stage;pair=PortraitReadbackPair.Submit(camera,root,width,studio,Style,ms=>CaptureWork(ms,"readback copy"));
    var submittedAt=Time.realtimeSinceStartup;while(!pair.Done){if(Time.realtimeSinceStartup-submittedAt>15)throw new TimeoutException("Portrait GPU readback timed out; resources retained until completion.");yield return null;}
    if(pair.Error!=null)throw pair.Error;
    var black=pair.Black!;var white=pair.White!;pair.Dispose();pair=null;
    bool linear=QualitySettings.activeColorSpace==ColorSpace.Linear;
    if(stage==3){
     processingSignature=signature;processingPlayer=player.GetPlayerID();processingGeneration=captureGeneration;processingSimplified=simplified;
     processing=Task.Run(()=>ProcessPortrait(black,white,1024,1536,UnityEngine.Experimental.Rendering.GraphicsFormat.R8G8B8A8_UNorm,linear));Status="processing";yield break;
    }
    probeProcessing=Task.Run(()=>{RuntimeArtPixels.ReconstructMatte(black,white,linear);return black;});
    while(!probeProcessing.IsCompleted)yield return null;
    var pixels=probeProcessing.GetAwaiter().GetResult();probeProcessing=null;
    if(stage==0||stage==2){
     if(!RuntimeArtPixels.HasVisibleContent(pixels)){
      if(!simplified&&UseFallback(renderers,fallbackMaterials,equippedRendererCount)){simplified=true;stage--;continue;}
      throw new EmptyPortraitException("Body-only asynchronous portrait pass was empty; image withheld.");
     }
    }else if(RuntimeArtPixels.TryPortraitFrame(pixels,width,width*3/2,out var cx,out var cy,out var scale)){
     var crop=Matrix4x4.identity;crop.m00=crop.m11=1/scale;crop.m03=-cx/scale;crop.m13=-cy/scale;camera.projectionMatrix=crop*camera.projectionMatrix;
    }
    yield return null;
   }
  }finally{
   if(root)root.SetActive(false);
   void Cleanup(){if(root)UnityEngine.Object.Destroy(root);if(studio)UnityEngine.Object.Destroy(studio);foreach(var material in fallbackMaterials)UnityEngine.Object.Destroy(material);foreach(var mesh in effectMeshes)UnityEngine.Object.Destroy(mesh);}
   if(pair!=null)pair.Retire(Cleanup);else Cleanup();
  }
 }
}
