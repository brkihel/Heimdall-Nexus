using System;
namespace Heimdall.Sagas.Mod;
// Pure timing policy: debounce equipment bursts, bounded retry, no timer-driven refresh.
internal sealed class PortraitRefresh {
 string observed="",completed="";double changedAt,nextAttempt;bool blocked;
 internal void Reset(){observed=completed="";changedAt=nextAttempt=0;blocked=false;}
 internal bool Due(string signature,double now,bool eligible=true){if(signature!=observed){observed=signature;changedAt=now;}if(!eligible){blocked=true;return false;}if(blocked){blocked=false;changedAt=now;}return now>=nextAttempt&&now-changedAt>=2&&signature!=completed;}
 internal void Defer(){blocked=true;}
 internal void Started(double now){nextAttempt=now+10;}
 internal void Completed(string signature,double now){completed=signature;}
 internal void Failed(double now){nextAttempt=now+60;}
}
