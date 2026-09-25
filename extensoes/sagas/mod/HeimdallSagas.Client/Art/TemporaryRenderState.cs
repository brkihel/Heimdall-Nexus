using System;
using System.Collections.Generic;

namespace Heimdall.Sagas.Mod;

/// <summary>Synchronous render-only overrides. Register restoration BEFORE any
/// mutation, including setters which could fail after changing native state.</summary>
internal sealed class TemporaryRenderState : IDisposable {
 readonly List<Action> restore=new List<Action>();
 bool disposed;
 public void Remember(Action undo){if(disposed)throw new ObjectDisposedException(nameof(TemporaryRenderState));restore.Add(undo);}
 public void Set<T>(Func<T> read,Action<T> write,T value){var previous=read();Remember(()=>write(previous));write(value);}
 public void Dispose(){
  if(disposed)return;disposed=true;
  List<Exception>? failures=null;
  for(int i=restore.Count-1;i>=0;i--)try{restore[i]();}catch(Exception ex){(failures??=new List<Exception>()).Add(ex);}
  restore.Clear();
  if(failures!=null)throw new AggregateException("Portrait render state restoration failed.",failures);
 }
}
