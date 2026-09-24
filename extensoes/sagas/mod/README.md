# Heimdall Sagas 0.1.3 preview

This is an original optional companion to Heimdall Nexus. It currently records
player presence, last known equipped items, opted-in live position, kills, deaths, and the world day. It does not
yet include the atlas, armory, leaderboards or AI stories.

The Client DLL is installed with BepInEx on each participating Valheim client.
The Bridge DLL is installed only on the Heimdall Nexus dedicated server. The
bridge does not open a web listener or bundle website files. The Nexus website
serves the public pages.

All three client sharing settings default to false. A player can independently
enable profile, map and position sharing in the BepInEx config. A live position
also requires Valheim's own map visibility. Events are recorded only while
profile sharing is enabled; locations require map sharing. Disabling profile
sharing removes queued local events and deletes retained events after the
client reconnects to deliver the updated consent. Disabling all three sharing
settings sends a full withdrawal that deletes the stored profile too.

Do not publish the client package to a mod store until a dedicated-server and
one-client playtest passes. Keep client and bridge on the same protocol version.
