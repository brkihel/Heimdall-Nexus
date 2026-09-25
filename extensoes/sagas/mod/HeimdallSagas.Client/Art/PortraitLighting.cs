using UnityEngine;
using UnityEngine.Rendering;

namespace Heimdall.Sagas.Mod;

internal static class PortraitLighting {
 // The installed Custom/Player forward shader reads UnityLighting and the
 // ambient/reflection probes. EnvMan additionally writes these globals for
 // other equipped materials. Change them only during our private Render call.
 static readonly int SunColor=Shader.PropertyToID("_SunColor"),AmbientColor=Shader.PropertyToID("_AmbientColor"),Wet=Shader.PropertyToID("_Wet");
 // A moderate diffuse floor reveals leather/cloth; the separate neutral
 // reflection below is essential for metallic armor, whose diffuse term is
 // deliberately small. Increasing the key alone just clips shiny highlights.
 // Studio values come from the client config (see PortraitStyle), so the look
 // can be tuned without rebuilding the plugin.
 public static void Render(Camera camera,PortraitStyle style,Cubemap? reflection=null){
  var Ambient=new Color(style.Ambient,style.Ambient,style.Ambient,1);
  bool owned=!reflection;if(owned)reflection=CreateStudioReflection();
  try{
  using(var state=new TemporaryRenderState()){
   var root=camera.transform.parent;
   foreach(var light in Object.FindObjectsByType<Light>(FindObjectsSortMode.None)){
    if(!light||light.transform.IsChildOf(root)||(light.cullingMask&camera.cullingMask)==0)continue;
    state.Set(()=>light.cullingMask,value=>{if(light)light.cullingMask=value;},light.cullingMask&~camera.cullingMask);
   }
   // Unity can prefer RenderSettings.sun as the main forward directional
   // source. Explicitly select our key as well as excluding the world mask.
   foreach(var light in root.GetComponentsInChildren<Light>())if(light.type==LightType.Directional){
    state.Set(()=>RenderSettings.sun,value=>RenderSettings.sun=value,light);break;
   }
   // Snapshot the complete coupled ambient state before the first setter.
   // The original SH probe is restored LAST because color/mode setters may
   // regenerate it. No DynamicGI.UpdateEnvironment, frame wait or coroutine.
   var probe=RenderSettings.ambientProbe;var mode=RenderSettings.ambientMode;
   var sky=RenderSettings.ambientSkyColor;var equator=RenderSettings.ambientEquatorColor;
   var ground=RenderSettings.ambientGroundColor;var intensity=RenderSettings.ambientIntensity;
   state.Remember(()=>RenderSettings.ambientProbe=probe);
   state.Remember(()=>RenderSettings.ambientIntensity=intensity);
   state.Remember(()=>RenderSettings.ambientGroundColor=ground);
   state.Remember(()=>RenderSettings.ambientEquatorColor=equator);
   state.Remember(()=>RenderSettings.ambientSkyColor=sky);
   state.Remember(()=>RenderSettings.ambientMode=mode);
   RenderSettings.ambientMode=AmbientMode.Flat;RenderSettings.ambientLight=Ambient;
   RenderSettings.ambientIntensity=1;
   var neutralProbe=new SphericalHarmonicsL2();neutralProbe.AddAmbientLight(Ambient.linear);RenderSettings.ambientProbe=neutralProbe;
   // Snapshot coupled reflection settings before any setter; restore the
   // original source mode before the original texture and intensity.
   var reflectionMode=RenderSettings.defaultReflectionMode;
   var reflectionTexture=RenderSettings.customReflectionTexture;
   var reflectionIntensity=RenderSettings.reflectionIntensity;
   state.Remember(()=>RenderSettings.reflectionIntensity=reflectionIntensity);
   state.Remember(()=>RenderSettings.customReflectionTexture=reflectionTexture);
   state.Remember(()=>RenderSettings.defaultReflectionMode=reflectionMode);
   RenderSettings.defaultReflectionMode=DefaultReflectionMode.Custom;
   RenderSettings.customReflectionTexture=reflection;
   RenderSettings.reflectionIntensity=style.Reflection;
   state.Set(()=>RenderSettings.fog,value=>RenderSettings.fog=value,false);
   state.Set(()=>Shader.GetGlobalColor(SunColor),value=>Shader.SetGlobalColor(SunColor,value),Color.black);
   state.Set(()=>Shader.GetGlobalColor(AmbientColor),value=>Shader.SetGlobalColor(AmbientColor,value),Ambient);
   state.Set(()=>Shader.GetGlobalFloat(Wet),value=>Shader.SetGlobalFloat(Wet,value),0f);
   camera.Render();
  }
  }finally{if(owned)Object.Destroy(reflection);}
 }
 internal static Cubemap CreateStudioReflection(){
  // Original procedural illumination, not the current world's sky/lighting.
  // HDR texture values are linear. A broad neutral ceiling and darker floor
  // give metal form without a sharp sun hotspot. Mips keep rough armor soft.
  // A tiny per-render texture avoids cached native resources surviving logout
  // or plugin teardown; it is destroyed after the original scene is restored.
  const int size=16;
  var cube=new Cubemap(size,TextureFormat.RGBAHalf,true){name="Sagas neutral studio reflection",hideFlags=HideFlags.HideAndDontSave,filterMode=FilterMode.Trilinear,wrapMode=TextureWrapMode.Clamp};
  try{
   for(int face=0;face<6;face++){
    var pixels=new Color[size*size];
    for(int y=0;y<size;y++)for(int x=0;x<size;x++){
     float u=(x+.5f)/size*2-1,v=(y+.5f)/size*2-1;
     // Cube face vertical direction, normalized identically across seams.
     float vertical=(face==2?1:face==3?-1:-v)/Mathf.Sqrt(1+u*u+v*v);
     float level=Mathf.Lerp(.18f,.42f,(vertical+1)*.5f);
     pixels[y*size+x]=new Color(level,level,level,1);
    }
    cube.SetPixels(pixels,(CubemapFace)face);
   }
   cube.Apply(true,true);return cube;
  }catch{Object.Destroy(cube);throw;}
 }
 public static void IsolateProbes(Renderer renderer){
  // These are inert copies. No world light/reflection probe sampling, and no
  // shared material modification (weapon emission remains the original).
  // ReflectionProbeUsage.Off still uses the scene's default reflection, which
  // Render temporarily replaces with our neutral studio cube.
  renderer.lightProbeUsage=LightProbeUsage.Off;
  renderer.reflectionProbeUsage=ReflectionProbeUsage.Off;
 }
}
