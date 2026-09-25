#!/usr/bin/env python3
"""Systemd timer entry point for server schedules."""
import operacoes
import sagas

if __name__ == '__main__':
    sagas.refresh_current_world(operacoes.GAME)
    operacoes.schedules_tick()
