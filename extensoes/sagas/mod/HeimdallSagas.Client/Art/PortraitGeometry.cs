using System;
namespace Heimdall.Sagas.Mod;
internal static class PortraitGeometry {
 internal static bool PlausibleSize(float original,float captured)=>!float.IsNaN(original)&&!float.IsNaN(captured)&&!float.IsInfinity(original)&&!float.IsInfinity(captured)&&original>.0001f&&captured>.0001f&&captured/original>=.1f&&captured/original<=10f;
 internal static bool PreferRigidBake(float original,float fullTransform,float rigidTransform){
  if(!PlausibleSize(original,rigidTransform))return false;
  if(!PlausibleSize(original,fullTransform))return true;
  return Math.Abs(Math.Log(rigidTransform/original))+.05<Math.Abs(Math.Log(fullTransform/original));
 }
 // Orbiting the original hierarchy avoids transforming skinned geometry. The
 // horizontal circumradius encloses every corner at any character-facing yaw.
 internal static float RotatingCameraDistance(float x,float y,float z,float aspect,float fieldOfView){
  if(x<0||z<0)throw new ArgumentException("Invalid portrait framing bounds.");
  float radius=(float)Math.Sqrt(x*x+z*z);
  return CameraDistance(radius,y,radius,aspect,fieldOfView);
 }
 internal static float CameraDistance(float x,float y,float z,float aspect,float fieldOfView){
  if(x<0||y<0||z<0||aspect<=0||fieldOfView<=0||fieldOfView>=179)throw new ArgumentException("Invalid portrait framing bounds.");
  double halfHeight=Math.Max(y,(x+z*.2)/aspect)*1.12;
  return (float)Math.Max(5,halfHeight/Math.Tan(fieldOfView*.5*Math.PI/180)+z+x*.2);
 }
}
