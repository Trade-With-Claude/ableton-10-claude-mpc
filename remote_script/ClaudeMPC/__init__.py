# -*- coding: utf-8 -*-
from __future__ import absolute_import

from .ClaudeMPC import ClaudeMPC


def create_instance(c_instance):
    return ClaudeMPC(c_instance)
