#!/usr/bin/env python3
"""Systemd timer entry point for server schedules."""
import operacoes

if __name__ == '__main__':
    operacoes.schedules_tick()
