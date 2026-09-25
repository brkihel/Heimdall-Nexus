using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using UnityEngine;

namespace Heimdall.Sagas.Mod;

// Optional, read-only adapter for installed Jewelcrafting 2.x. Never loads the
// mod DLL itself or scans assemblies, and never opens item-container inventories.
internal static class JewelcraftingAdapter {
 internal static bool Installed=>Api!=null;
 const string Guid="org.bepinex.plugins.jewelcrafting";
 static readonly Type? Api=OptionalTypes.InPlugin(Guid,"Jewelcrafting.API");
 static readonly MethodInfo? GetGems=Api?.GetMethod("GetGems",new[]{typeof(ItemDrop.ItemData)}),GetColor=Api?.GetMethod("GetSocketableItemColor",new[]{typeof(ItemDrop.ItemData)}),GetJewelry=Api?.GetMethod("GetEquippedJewelry",new[]{typeof(Player)});
 static readonly Type? Gem=Api?.GetNestedType("GemInfo"),Visual=OptionalTypes.InPlugin(Guid,"Jewelcrafting.Visual");
 static readonly FieldInfo? Prefab=Gem?.GetField("gemPrefab"),Ranges=Gem?.GetField("gemEffectsPowerRange"),Finger=Visual?.GetField("equippedFingerItem"),Neck=Visual?.GetField("equippedNeckItem");
 static readonly FieldInfo? ArmorJewelry=OptionalTypes.InPlugin(Guid,"Jewelcrafting.JewelrySetup")?.GetField("upgradeableJewelry");
 internal static bool HasArmor(ItemDrop.ItemData item){try{return ArmorJewelry?.GetValue(null) is IEnumerable<string> names&&names.Contains(item.m_shared.m_name);}catch{Failed();return false;}}
 static float nextWarning;
 static void Failed(){if(Time.unscaledTime<nextWarning)return;nextWarning=Time.unscaledTime+60;Debug.LogWarning("Heimdall Sagas: optional Jewelcrafting details unavailable; ordinary equipment sharing continues.");}
 static string Clean(string? value,int max){var s=Regex.Replace(value??"","<[^>]*>","");s=new string(s.Select(c=>char.IsControl(c)?' ':c).ToArray());return s.Length<=max?s:s.Substring(0,max);}

 // Sockets of one item; each gem keeps its prefab so its icon can be requested.
 internal static List<(GemSocket Socket,ItemDrop.ItemData? Gem)> Read(ItemDrop.ItemData item,out string color){
  var sockets=new List<(GemSocket,ItemDrop.ItemData?)>();color="";if(Api==null)return sockets;
  if(GetGems==null||GetColor==null||Prefab==null||Ranges==null){Failed();return sockets;}
  try{
   // A color exists only for socketable equipment. GetGems also supports
   // boxes/bags: never invoke it for those, their contents are not equipment.
   if(!(GetColor.Invoke(null,new object[]{item}) is Color shade))return sockets;
   color="#"+ColorUtility.ToHtmlStringRGB(shade);
   if(!(GetGems.Invoke(null,new object[]{item}) is IEnumerable gems))return sockets;
   foreach(var gem in gems){
    if(sockets.Count>=11)break;var socket=new GemSocket();ItemDrop.ItemData? data=null;
    if(gem!=null){
     var prefabName=Clean(Prefab.GetValue(gem) as string,200);
     var prefab=ObjectDB.instance&&prefabName!=""?ObjectDB.instance.GetItemPrefab(prefabName):null;
     data=prefab?prefab!.GetComponent<ItemDrop>()?.m_itemData:null;
     socket.name=Clean(data!=null?GearReader.Localize(data.m_shared.m_name):prefabName,120);
     var effects=new List<string>();
     if(Ranges.GetValue(gem) is IDictionary ranges)foreach(DictionaryEntry entry in ranges){
      if(effects.Count>=8)break;if(!(entry.Value is float[] powers)||powers.Length<2||powers.Any(v=>float.IsNaN(v)||float.IsInfinity(v)))continue;
      // The public API exposes the configured range, not the seeded roll.
      var lo=powers[0].ToString("0.##",CultureInfo.InvariantCulture);var hi=powers[1].ToString("0.##",CultureInfo.InvariantCulture);
      effects.Add(Clean(entry.Key?.ToString(),120)+": "+(lo==hi?lo:lo+"–"+hi));
     }
     socket.effects=effects.ToArray();
    }
    sockets.Add((socket,data));
   }
  }catch{Failed();}
  return sockets;
 }
 static (ItemDrop.ItemData? finger,ItemDrop.ItemData? neck) Jewelry(Player player){
  if(GetJewelry==null)return (null,null);
  try{var visual=GetJewelry.Invoke(null,new object[]{player});return visual==null?(null,null):(Finger?.GetValue(visual) as ItemDrop.ItemData,Neck?.GetValue(visual) as ItemDrop.ItemData);}catch{Failed();return (null,null);}
 }
 internal static List<ItemDrop.ItemData> Equipped(Player player){
  var items=player.GetInventory().GetEquippedItems();var jewelry=Jewelry(player);
  if(jewelry.finger!=null&&!items.Contains(jewelry.finger))items.Add(jewelry.finger);
  if(jewelry.neck!=null&&!items.Contains(jewelry.neck))items.Add(jewelry.neck);
  return items;
 }
 internal static void JewelrySlot(GearItem gear,ItemDrop.ItemData item,Player player){
  if(GetJewelry==null)return;var jewelry=Jewelry(player);
  if(ReferenceEquals(item,jewelry.finger)){gear.slot="Ring";gear.equipped=true;}
  else if(ReferenceEquals(item,jewelry.neck)){gear.slot="Necklace";gear.equipped=true;}
 }
}
