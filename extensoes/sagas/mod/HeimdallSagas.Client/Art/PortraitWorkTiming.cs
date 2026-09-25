using System;
namespace Heimdall.Sagas.Mod;
internal sealed class PortraitWorkTiming {
 int frame=-1;double current;internal double Maximum{get;private set;}
 internal void Reset(){frame=-1;current=Maximum=0;}
 internal void Add(int frameIndex,double milliseconds){if(frame!=frameIndex){frame=frameIndex;current=0;}current+=Math.Max(0,milliseconds);Maximum=Math.Max(Maximum,current);}
}
