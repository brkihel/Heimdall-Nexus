using System;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Reflection;
using System.Linq;
using HarmonyLib;
using Debug=UnityEngine.Debug;
using UnityEngine;

namespace Heimdall.Sagas.Mod;

/// <summary>Local runtime-only artwork: item icons and the character portrait.
/// Construct/call on Unity's main thread. Callers MUST apply profile-sharing
/// consent before requesting or transmitting art. No installed textures or
/// character assets are bundled with the mod.</summary>
internal sealed partial class RuntimeArt {
 internal sealed class Image {
  public string Id="", Kind="";
  public byte[] Png=Array.Empty<byte>();
  public int Width,Height;
 }
 const int MaximumBytes=MediaLimits.IconBytes, MaximumIcons=128;
 readonly int thread=Thread.CurrentThread.ManagedThreadId;
 readonly Action<string,Exception> warn;
 readonly Dictionary<int,Image> icons=new Dictionary<int,Image>();
 static int lastIconFrame=-1;
 readonly Queue<int> iconOrder=new Queue<int>();
 readonly Queue<(int Key,Sprite Sprite)> iconRequests=new Queue<(int,Sprite)>();readonly HashSet<int> requestedIcons=new HashSet<int>();double iconBatchMaximum;
 Image? portrait;
 long portraitPlayer;
 readonly PortraitRefresh refresh=new PortraitRefresh();
 Task<PortraitResult>? processing;string processingSignature="";long processingPlayer;int generation,processingGeneration;bool forceSimplified,processingSimplified;
 sealed class PortraitResult {internal Image Image=null!;internal double MatteMs,EncodeMs;}
 static readonly FieldInfo[] appearanceFields=new[]{"m_modelIndex","m_skinColor","m_hairColor","m_beardItem","m_hairItem","m_leftItem","m_rightItem","m_chestItem","m_legItem","m_helmetItem","m_shoulderItem","m_utilityItem","m_trinketItem","m_leftBackItem","m_rightBackItem"}.Select(n=>AccessTools.Field(typeof(VisEquipment),n)).Where(f=>f!=null).ToArray();
 static bool Standing(Player player)=>!player.IsSitting()&&!player.IsAttached();
 static string Appearance(Player player){
  var text=new StringBuilder();var visual=player.GetComponentInChildren<VisEquipment>();
  if(visual)foreach(var field in appearanceFields)text.Append(field.Name).Append('=').Append(field.GetValue(visual)).Append(';');
  foreach(var item in JewelcraftingAdapter.Equipped(player).OrderBy(i=>i.m_shared.m_itemType).ThenBy(i=>i.m_shared.m_name)){
   text.Append(item.m_dropPrefab?item.m_dropPrefab.name:item.m_shared.m_name).Append(':').Append(item.m_quality).Append(':').Append(item.m_variant).Append(';');
   foreach(var pair in item.m_customData.OrderBy(p=>p.Key))text.Append(pair.Key).Append('=').Append(pair.Value).Append(';');
  }return text.ToString();
 }

 internal bool CaptureBusy=>capture!=null;
 public string Status {get;private set;}="waiting-for-player";
 // The current world id and the tunable studio, owned by the plugin.
 internal Func<string> World=()=>"";
 internal PortraitStyle Style=new PortraitStyle();
 public RuntimeArt(Action<string,Exception> warning){warn=warning;}
 // A manual refresh (config hotkey) redraws the portrait with the current style.
 public void ForceRefresh(){CheckThread();CancelCapture();refresh.Reset();forceSimplified=false;Status="refresh-requested";}
 void CheckThread(){if(Thread.CurrentThread.ManagedThreadId!=thread)throw new InvalidOperationException("Runtime artwork requires Unity's main thread.");}
 public void Clear(){CheckThread();CancelCapture();iconRequests.Clear();requestedIcons.Clear();iconBatchMaximum=0;icons.Clear();iconOrder.Clear();portrait=null;portraitPlayer=0;generation++;refresh.Reset();forceSimplified=false;Status="waiting-for-player";}

 public Image? TryIcon(ItemDrop.ItemData item) {
  CheckThread();try{if(item.m_shared.m_icons==null||item.m_variant<0||item.m_variant>=item.m_shared.m_icons.Length)return null;
  var sprite=item.GetIcon();if(!sprite||!sprite.texture)return null;int key=sprite.GetInstanceID();
  if(icons.TryGetValue(key,out var known))return known;
  if(requestedIcons.Count<MaximumIcons&&requestedIcons.Add(key))iconRequests.Enqueue((key,sprite));
  return null;}catch(Exception e){warn("item icon request",e);return null;}
 }
 public void PumpIcons(bool permitted){
  CheckThread();if(!permitted){iconRequests.Clear();requestedIcons.Clear();return;}if(capture!=null||iconRequests.Count==0||lastIconFrame==Time.frameCount)return;lastIconFrame=Time.frameCount;
  var timer=Stopwatch.StartNew();var request=iconRequests.Dequeue();requestedIcons.Remove(request.Key);if(request.Sprite)CaptureIcon(request.Sprite);
  iconBatchMaximum=Math.Max(iconBatchMaximum,timer.Elapsed.TotalMilliseconds);
  if(iconRequests.Count==0){Debug.Log("Sagas icon queue drained: max one-icon main-thread work="+iconBatchMaximum.ToString("F1")+" ms.");iconBatchMaximum=0;}
 }
 Image? CaptureIcon(Sprite sprite){
  try {if(!sprite||!sprite.texture)return null;int key=sprite.GetInstanceID();
   var rect=sprite.textureRect;
   var source=sprite.texture;
   int width=Mathf.Clamp(Mathf.RoundToInt(rect.width),1,96),height=Mathf.Clamp(Mathf.RoundToInt(rect.height),1,96);
   var rt=RenderTexture.GetTemporary(width,height,0,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB);
   Image? result;
   var previous=RenderTexture.active;
   try {
    Graphics.Blit(source,rt,new Vector2(rect.width/source.width,rect.height/source.height),new Vector2(rect.x/source.width,rect.y/source.height));
    result=Encode(rt,"icon");
   }finally{RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);}
   if(result==null)return null;
   if(icons.Count>=MaximumIcons)icons.Remove(iconOrder.Dequeue());
   icons[key]=result;iconOrder.Enqueue(key);return result;
  }catch(Exception ex){warn("item artwork",ex);return null;}
 }

 public Image? TryPortrait(Player player,bool allowRefresh=true) {
  CheckThread();
  if(!player){Status="waiting-for-player";return null;}
  if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null){Status="no-graphics-device";return null;}
  long id=player.GetPlayerID();var now=Time.realtimeSinceStartup;
  if(portraitPlayer!=id){portrait=null;portraitPlayer=id;generation++;refresh.Reset();forceSimplified=false;}
  var signature=Appearance(player);var due=refresh.Due(signature,now,Standing(player));
  if(capture!=null)return portrait;
  if(processing!=null){
   if(!processing.IsCompleted)return portrait;
   var job=processing;processing=null;
   if(processingGeneration==generation&&processingPlayer==id&&processingSignature==signature&&Standing(player)){
    if(job.IsFaulted){forceSimplified=true;refresh.Failed(now);Status="processing-failed";warn("portrait processing",job.Exception!);}
    else{var result=job.Result;portrait=result.Image;Status=processingSimplified?"simplified":"ready";forceSimplified=false;refresh.Completed(signature,now);Debug.Log("Sagas portrait timings: background matte="+result.MatteMs.ToString("F1")+" ms, encode/hash="+result.EncodeMs.ToString("F1")+" ms; ready "+portrait.Width+"x"+portrait.Height+", "+portrait.Png.Length+" bytes.");}
   }else{_ = job.Exception;Status="appearance-changed";}
   return portrait;
  }
  if(!SystemInfo.supportsAsyncGPUReadback){Status="async-readback-unavailable";return portrait;}
  if(probeProcessing!=null){if(!probeProcessing.IsCompleted)return portrait;_ = probeProcessing.Exception;probeProcessing=null;}
  if(!allowRefresh||!due||PortraitReadbackPair.PendingRequests!=0)return portrait;
  refresh.Started(now);Status="preparing";
  captureSignature=signature;capturePlayer=player;captureWorld=World();captureGeneration=generation;captureStarted=now;captureTiming.Reset();capturePhaseMax.Clear();captureSteps=0;
  capture=BuildPortrait(player,signature).GetEnumerator();return portrait;
 }

 // Freeze attached visual effects into inert meshes. Never clone effect scripts,
 // advance live particle simulation or change the source renderer/light. Baking
 // both matte passes from the same snapshot avoids flickering opacity edges.
 IEnumerable<object?> CaptureEffects(Player player,GameObject root,Camera camera,int layer,Bounds bodyBounds,List<Renderer> renderers,List<Mesh> meshes,StringBuilder diagnostics,Dictionary<Transform,FrozenPose> frozen,Dictionary<Transform,Transform> poses,Vector3 frozenPosition){
  int captured=0,vertices=0,skipped=0,lights=0,attempts=0;
  var allowed=bodyBounds;allowed.Expand(4f);
  Matrix4x4 FreezeMatrix(Renderer source)=>CopyFrozenPose(source.transform,root.transform,poses,frozen,layer).localToWorldMatrix*source.transform.worldToLocalMatrix;
  Bounds Shift(Renderer source){var m=FreezeMatrix(source);var b=source.bounds;var e=b.extents;var x=m.MultiplyVector(new Vector3(e.x,0,0));var y=m.MultiplyVector(new Vector3(0,e.y,0));var z=m.MultiplyVector(new Vector3(0,0,e.z));return new Bounds(m.MultiplyPoint3x4(b.center),new Vector3(Math.Abs(x.x)+Math.Abs(y.x)+Math.Abs(z.x),Math.Abs(x.y)+Math.Abs(y.y)+Math.Abs(z.y),Math.Abs(x.z)+Math.Abs(y.z)+Math.Abs(z.z))*2);}
  bool InBounds(Renderer source){var b=Shift(source);return allowed.Contains(b.min)&&allowed.Contains(b.max)&&b.size.sqrMagnitude>0;}
  void Add(Renderer source,Mesh mesh,Material? material,bool worldSpace){
   if(!mesh||mesh.vertexCount==0||!material)return;
   if(captured>=24||mesh.vertexCount>32768-vertices){skipped++;return;}
   GameObject node;
   if(worldSpace){node=new GameObject("Sagas frozen equipment effect"){hideFlags=HideFlags.HideAndDontSave,layer=layer};node.transform.SetParent(root.transform,false);var matrix=FreezeMatrix(source);var positions=mesh.vertices;for(int i=0;i<positions.Length;i++)positions[i]=matrix.MultiplyPoint3x4(positions[i]);mesh.vertices=positions;mesh.RecalculateBounds();}
   else node=CopyFrozenPose(source.transform,root.transform,poses,frozen,layer).gameObject;
   // A trail and its particles must have distinct renderer components even
   // when the source shares one transform.
   if(node.GetComponent<MeshRenderer>()){
    var child=new GameObject("Sagas frozen effect trail"){hideFlags=HideFlags.HideAndDontSave,layer=layer};child.transform.SetParent(node.transform,false);node=child;
   }
   node.AddComponent<MeshFilter>().sharedMesh=mesh;
   var copy=node.AddComponent<MeshRenderer>();copy.sharedMaterial=material;
   var properties=new MaterialPropertyBlock();source.GetPropertyBlock(properties);copy.SetPropertyBlock(properties);
   var perMaterial=new MaterialPropertyBlock();source.GetPropertyBlock(perMaterial,0);copy.SetPropertyBlock(perMaterial,0);
   PortraitLighting.IsolateProbes(copy);
   copy.shadowCastingMode=UnityEngine.Rendering.ShadowCastingMode.Off;copy.receiveShadows=false;copy.bounds=Shift(source);
   renderers.Add(copy);captured++;vertices+=mesh.vertexCount;
  }
  Mesh NewMesh(){var mesh=new Mesh{name="Sagas frozen effect mesh",hideFlags=HideFlags.HideAndDontSave};meshes.Add(mesh);return mesh;}
  foreach(var source in player.GetComponentsInChildren<ParticleSystemRenderer>()){
   yield return null;
   if(captured>=24||attempts++>=32)break;
   var system=source.GetComponent<ParticleSystem>();
   if(!source.enabled||!source.gameObject.activeInHierarchy||!system||system.particleCount==0)continue;
   if(system.particleCount>2048||!InBounds(source)){skipped++;continue;}
   // Bound mesh-particle expansion before entering native BakeMesh, not only
   // after allocating its output. Billboard quads need four vertices each.
   long perParticle=4;
   if(source.renderMode==ParticleSystemRenderMode.Mesh){
    if(source.meshCount>16){skipped++;continue;}
    var sourceMeshes=new Mesh[source.meshCount];source.GetMeshes(sourceMeshes);
    foreach(var sourceMesh in sourceMeshes)if(sourceMesh)perParticle=Math.Max(perParticle,sourceMesh.vertexCount);
   }
   if(perParticle*system.particleCount>32768-vertices){skipped++;continue;}
   try{
    // Installed Unity6 options explicitly bake translation AND rotation/scale;
    // the destination stays at identity in world space, avoiding double scale.
    var options=ParticleSystemBakeMeshOptions.BakeRotationAndScale|ParticleSystemBakeMeshOptions.BakePosition;
    if(source.renderMode!=ParticleSystemRenderMode.None){var mesh=NewMesh();source.BakeMesh(mesh,camera,options);Add(source,mesh,source.sharedMaterial,true);}
    // Particle trail history has no cheap reliable pre-bake vertex budget.
    // Preserve its particles; skip that unbounded history in this still image.
    if(system.trails.enabled)skipped++;
   }catch(Exception ex){skipped++;warn("portrait attached particle snapshot",ex);}
  }
  foreach(var source in player.GetComponentsInChildren<TrailRenderer>()){
   yield return null;
   if(captured>=24||attempts++>=32)break;
   if(!source.enabled||!source.gameObject.activeInHierarchy||source.positionCount<2)continue;
   long trailVertices=((long)source.positionCount*(2L+source.numCornerVertices)+2L*source.numCapVertices)*2;
   if(source.positionCount>2048||trailVertices>32768-vertices||!InBounds(source)){skipped++;continue;}
   try{var mesh=NewMesh();source.BakeMesh(mesh,camera,false);Add(source,mesh,source.sharedMaterial,false);}
   catch(Exception ex){skipped++;warn("portrait attached trail snapshot",ex);}
  }
  foreach(var source in player.GetComponentsInChildren<Light>()){
   yield return null;
   if(lights>=8)break;
   if(!source.enabled||!source.gameObject.activeInHierarchy||source.intensity<=0||!allowed.Contains(CopyFrozenPose(source.transform,root.transform,poses,frozen,layer).position)||(source.type!=LightType.Point&&source.type!=LightType.Spot))continue;
   // Always freeze attached lights. The render scope excludes ALL original
   // scene lights from the capture layer, preventing sunlight and duplicates.
   var node=new GameObject("Sagas frozen equipment light"){hideFlags=HideFlags.HideAndDontSave,layer=layer};node.transform.SetParent(root.transform,false);
   var frozenLight=CopyFrozenPose(source.transform,root.transform,poses,frozen,layer);node.transform.SetPositionAndRotation(frozenLight.position,frozenLight.rotation);
   var copy=node.AddComponent<Light>();copy.type=source.type;copy.color=source.color;copy.intensity=Mathf.Clamp(source.intensity,0,8);copy.range=Mathf.Clamp(source.range,0,20);
   copy.useColorTemperature=source.useColorTemperature;copy.colorTemperature=source.colorTemperature;
   copy.spotAngle=source.spotAngle;copy.innerSpotAngle=source.innerSpotAngle;copy.cullingMask=1<<layer;copy.shadows=LightShadows.None;lights++;
  }
  diagnostics.Append(" frozen-effects=").Append(captured).Append(" effect-vertices=").Append(vertices).Append(" attached-lights=").Append(lights).Append(" skipped-effects=").Append(skipped).Append(';');
 }

 // Detached byte arrays only. EncodeArrayToPNG is documented thread-safe; no Texture2D/native-array access here.
 static PortraitResult ProcessPortrait(byte[] black,byte[] white,int width,int height,UnityEngine.Experimental.Rendering.GraphicsFormat format,bool linear){
  var clock=Stopwatch.StartNew();RuntimeArtPixels.ReconstructMatte(black,white,linear);
  if(!RuntimeArtPixels.CanPublishPortrait(true,black))throw new EmptyPortraitException("Processed portrait has insufficient visible geometry.");
  var matteMs=clock.Elapsed.TotalMilliseconds;clock.Restart();
  foreach(var size in new[]{width,768,512,341,256,192,128,96}){
   if(size>width)continue;var h=size*3/2;var pixels=size==width?black:RuntimeArtPixels.ResizePortrait(black,width,height,size,h);
   var bytes=ImageConversion.EncodeArrayToPNG(pixels,format,(uint)size,(uint)h);
   if(bytes.Length>MediaLimits.PortraitBytes)continue;
   using var hash=SHA256.Create();return new PortraitResult{Image=new Image{Id=BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-","").ToLowerInvariant(),Kind="portrait",Png=bytes,Width=size,Height=h},MatteMs=matteMs,EncodeMs=clock.Elapsed.TotalMilliseconds};
  }throw new InvalidOperationException("Portrait exceeds upload size bound.");
 }

 static Image? Encode(RenderTexture source,string kind) {
  var texture=new Texture2D(source.width,source.height,TextureFormat.RGBA32,false){hideFlags=HideFlags.HideAndDontSave};
  try {
   RenderTexture.active=source;texture.ReadPixels(new Rect(0,0,source.width,source.height),0,0,false);
   var bytes=ImageConversion.EncodeToPNG(texture);if(bytes.Length>MaximumBytes)return null;
   using(var hash=SHA256.Create())return new Image{Id=BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-","").ToLowerInvariant(),Kind=kind,Png=bytes,Width=source.width,Height=source.height};
  }finally{UnityEngine.Object.Destroy(texture);}
 }

 sealed class EmptyPortraitException:Exception {public EmptyPortraitException(string message):base(message){}}
 static bool UseFallback(List<Renderer> renderers,List<Material> owned,int equippedCount){
  var shader=Shader.Find("Unlit/Texture");if(!shader||!shader.isSupported)shader=Shader.Find("Standard");
  if(!shader||!shader.isSupported)return false;
  // Transparent effect shaders must survive fallback; replacing a glow quad
  // with an opaque texture shader would cover the character with rectangles.
  for(int index=0;index<Math.Min(equippedCount,renderers.Count);index++){
   var renderer=renderers[index];
   var originals=renderer.sharedMaterials;var replacements=new Material[originals.Length];
   for(int i=0;i<originals.Length;i++){
    var source=originals[i];var material=new Material(shader){hideFlags=HideFlags.HideAndDontSave};owned.Add(material);replacements[i]=material;
    if(source){material.mainTexture=source.mainTexture;material.mainTextureScale=source.mainTextureScale;material.mainTextureOffset=source.mainTextureOffset;
     if(material.HasProperty("_Color")){var color=source.HasProperty("_Color")?source.GetColor("_Color"):Color.white;if(source.HasProperty("_SkinColor"))color*=source.GetColor("_SkinColor");color.a=1;material.SetColor("_Color",color);}}
    if(material.HasProperty("_Glossiness"))material.SetFloat("_Glossiness",0);
    renderer.SetPropertyBlock(null,i);
   }
   renderer.SetPropertyBlock(null);renderer.sharedMaterials=replacements;
  }
  return true;
 }

}
