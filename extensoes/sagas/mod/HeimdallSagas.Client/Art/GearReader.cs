using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;

namespace Heimdall.Sagas.Mod;

// What the profile page shows about one item, read through the installed game
// (and mod) APIs. Callers own the ShareProfile consent.
internal static class GearReader {
 const int MaximumStats=16, MaximumEffects=12;
 static readonly string[] ArmorTypes={"Helmet","Chest","Legs","Shoulder","Hands"};
 static readonly FieldInfo[] damageFields=typeof(HitData.DamageTypes).GetFields(BindingFlags.Public|BindingFlags.Instance).Where(f=>f.FieldType==typeof(float)).ToArray();

 internal static string Localize(string value)=>Localization.instance==null?value:Localization.instance.Localize(value);
 internal static string Clean(string? value,int max){var s=Regex.Replace(value??"","<[^>]*>","");s=new string(s.Where(c=>!char.IsControl(c)).ToArray()).Trim();return s.Length<=max?s:s.Substring(0,max);}

 internal static GearItem Read(ItemDrop.ItemData item,Player player,Func<ItemDrop.ItemData,string> icon){
  var type=item.m_shared.m_itemType.ToString();
  var gear=new GearItem{name=Clean(Localize(item.m_shared.m_name),120),slot=Clean(type,40),type=Clean(type,40),
   prefab=Clean(item.m_dropPrefab?item.m_dropPrefab.name:"",80),quality=Math.Max(1,Math.Min(1000,item.m_quality)),
   durability=Finite(item.m_durability,0,100000),max_durability=Finite(item.GetMaxDurability(),0,100000),
   equipped=item.m_equipped};
  var stats=new List<Stat>();
  void Add(string name,float value){if(stats.Count<MaximumStats&&value!=0&&!float.IsNaN(value)&&!float.IsInfinity(value))stats.Add(new Stat{name=name,value=value});}
  if(ArmorTypes.Contains(type)||JewelcraftingAdapter.HasArmor(item))Add("Armor",item.GetArmor());
  if(item.IsWeapon()||type=="Shield")Add("Block",item.GetBlockPower(0));
  var damage=item.GetDamage();foreach(var field in damageFields)Add("Damage "+field.Name.Replace("m_",""),(float)field.GetValue(damage));
  Add("Movement",item.m_shared.m_movementModifier);
  gear.stats=stats.ToArray();
  var effects=new List<string>();
  foreach(var mod in item.m_shared.m_damageModifiers){if(effects.Count>=MaximumEffects)break;effects.Add(mod.m_type+": "+mod.m_modifier);}
  if(item.m_shared.m_setStatusEffect&&effects.Count<MaximumEffects)
   effects.Add("Set "+item.m_shared.m_setSize+": "+Clean(Localize(item.m_shared.m_setStatusEffect.m_name),80));
  gear.effects=effects.ToArray();
  var sockets=JewelcraftingAdapter.Read(item,out var color);
  gear.socket_color=color;
  foreach(var (socket,gem) in sockets)if(gem!=null)socket.icon=icon(gem);
  gear.sockets=sockets.Select(s=>s.Socket).ToArray();
  JewelcraftingAdapter.JewelrySlot(gear,item,player);
  // Held weapons, shields, torches and the selected ammunition.
  gear.active=ReferenceEquals(item,player.RightItem)||ReferenceEquals(item,player.LeftItem)||ReferenceEquals(item,player.GetAmmoItem());
  gear.icon=icon(item);
  return gear;
 }

 // Mirrors the game's hotkey bar: numbered slots 1–8 only, never the rest of
 // the inventory.
 internal static GearItem[] Hotbar(Player player,Func<ItemDrop.ItemData,string> icon){
  var bound=new List<ItemDrop.ItemData>();player.GetInventory().GetBoundItems(bound);
  return bound.Where(i=>i!=null&&i.m_shared!=null&&i.m_gridPos.y==0&&i.m_gridPos.x>=0&&i.m_gridPos.x<8)
   .GroupBy(i=>i.m_gridPos.x).OrderBy(g=>g.Key).Select(g=>{var gear=Read(g.First(),player,icon);gear.hotbar=g.Key+1;return gear;}).ToArray();
 }

 static float Finite(float value,float min,float max)=>float.IsNaN(value)||float.IsInfinity(value)?0:Math.Max(min,Math.Min(max,value));
}
