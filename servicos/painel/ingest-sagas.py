#!/usr/bin/env python3
"""Import completed bridge packets into the optional Heimdall Sagas store."""
import json

import sagas


if __name__ == '__main__':
    print(json.dumps(sagas.process_inbox(), separators=(',', ':')))
