# Heimdall Sagas preview (Client 0.2.1, Bridge 0.2.1)

This is an original optional companion to Heimdall Nexus. It currently records
player presence, last known equipped items, opted-in live position, kills, deaths,
and the world day. The Nexus can create optional AI stories from consented
events and generate a Birds Eye world map. Armory and leaderboards are planned.

The Client DLL is installed with BepInEx on each participating Valheim client.
The Bridge DLL is installed only on the Heimdall Nexus dedicated server. The
bridge does not open a web listener or bundle website files. The Nexus website
serves the public pages.

All four client sharing settings default to false. A player can independently
enable profile, map, position and story sharing in the BepInEx config. Story
sharing also requires profile sharing and allows the administrator's selected
AI provider to receive the Viking name and selected shared event facts for public
AI stories. A live position
also requires Valheim's own map visibility. Events are recorded only while
profile sharing is enabled; locations require map sharing. Disabling profile
sharing removes queued local events and deletes retained events after the
client reconnects to deliver the updated consent. Disabling profile, map and
position sharing sends a full withdrawal that deletes the stored profile too.
Turning off story sharing deletes chapters that refer to that Viking.

Do not publish the client package to a mod store until a dedicated-server and
one-client playtest passes. Keep client and bridge on the same protocol version.
