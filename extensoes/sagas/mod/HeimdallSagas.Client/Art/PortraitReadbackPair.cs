using System;
using System.Threading;
using System.Diagnostics;
using UnityEngine;
using UnityEngine.Rendering;
namespace Heimdall.Sagas.Mod;
// Callback copies data during its valid frame. Textures remain leased until GPU completion, even after cancellation.
internal sealed class PortraitReadbackPair : IDisposable {
 static int pending;
 internal static int PendingRequests=>Volatile.Read(ref pending);
 readonly bool[] done=new bool[2],started=new bool[2];bool abandoned;readonly ReadbackLifetime lifetime=new ReadbackLifetime();
 Action<double>? reportCpu;
 internal byte[]? Black,White;internal Exception? Error;
 internal bool Done=>done[0]&&done[1];
 internal static PortraitReadbackPair Submit(Camera camera,GameObject root,int width,Cubemap studio,PortraitStyle style,Action<double> reportCpu){
  var pair=new PortraitReadbackPair{reportCpu=reportCpu};var oldTarget=camera.targetTexture;var oldActive=RenderTexture.active;var oldColor=camera.backgroundColor;
  try{
   root.SetActive(true);
   for(int i=0;i<2;i++){
    int slot=i;var target=RenderTexture.GetTemporary(width,width*3/2,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB);bool submitted=false;
    try{
     if(!target||(!target.IsCreated()&&!target.Create()))throw new InvalidOperationException("Portrait render target unavailable.");
     camera.targetTexture=target;camera.backgroundColor=i==0?new Color(0,0,0,0):new Color(1,1,1,0);PortraitLighting.Render(camera,style,studio);
     Interlocked.Increment(ref pending);pair.lifetime.Begin();
     try{AsyncGPUReadback.Request(target,0,TextureFormat.RGBA32,request=>pair.Complete(slot,target,request));submitted=true;pair.started[slot]=true;}
     catch{Interlocked.Decrement(ref pending);pair.lifetime.Complete();throw;}
    }finally{if(!submitted){if(target)RenderTexture.ReleaseTemporary(target);pair.done[slot]=true;}}
   }
   return pair;
  }catch(Exception error){pair.Error=error;for(int i=0;i<2;i++)if(!pair.started[i])pair.done[i]=true;return pair;}
  finally{camera.targetTexture=oldTarget;camera.backgroundColor=oldColor;RenderTexture.active=oldActive;root.SetActive(false);}
 }
 void Complete(int slot,RenderTexture target,AsyncGPUReadbackRequest request){
  var clock=Stopwatch.StartNew();
  try{if(!abandoned&&Error==null){if(request.hasError)throw new InvalidOperationException("Portrait asynchronous GPU readback failed.");var native=request.GetData<byte>();var copy=new byte[native.Length];native.CopyTo(copy);if(slot==0)Black=copy;else White=copy;}}
  catch(Exception e){Error=e;}
  finally{done[slot]=true;try{if(target)RenderTexture.ReleaseTemporary(target);}finally{Interlocked.Decrement(ref pending);try{lifetime.Complete();}finally{reportCpu?.Invoke(clock.Elapsed.TotalMilliseconds);}}}
 }
 internal void Retire(Action release){Dispose();lifetime.Retire(release);}
 public void Dispose(){abandoned=true;Black=White=null;}
}
