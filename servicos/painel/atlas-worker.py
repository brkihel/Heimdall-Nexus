#!/usr/bin/python3
"""Render and tile the Birds Eye world map when the bridge exports a new world."""
import json

import atlas

if __name__ == '__main__':
    published = atlas.publish()
    if published:
        print(json.dumps({'published': published}))
