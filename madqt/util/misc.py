# encoding: utf-8
"""
Misc programming toolbox.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import functools


__all__ = [
    'safe_hasattr',
    'attribute_alias',
    'memoize',
    'cachedproperty',
    'update_property',
    'Property',
    'rename_key',
    'merged',
    'translate_default',
]


def safe_hasattr(obj, key):
    """
    Safe replacement for `hasattr()`. The py2 builtin `hasattr()` shadows all
    exceptions, see https://hynek.me/articles/hasattr/.
    """
    try:
        getattr(obj, key)
        return True
    except AttributeError:
        return False


# class utils

def attribute_alias(alias):
    """Declare alias for an instance variable / attribute."""
    return property(
        lambda self:        getattr(self, alias),
        lambda self, value: setattr(self, alias, value),
        lambda self:        delattr(self, alias),
        "Alias for '{}'".format(alias))


def memoize(func):
    key = '_' + func.__name__
    @functools.wraps(func)
    def get(self):
        try:
            return getattr(self, key)
        except AttributeError:
            val = func(self)
            setattr(self, key, val)
            return val
    return get


def cachedproperty(func):
    """A memoize decorator for class properties."""
    return property(memoize(func))


def update_property(update, name=None):
    key = '_' + update.__name__
    @functools.wraps(update)
    def wrapper(self, *args, **kwargs):
        old = getattr(self, key, None)
        new = update(self, old, *args, **kwargs)
        setattr(self, key, new)
        return new
    return wrapper


class Property(object):

    def __init__(self, obj, construct):
        self.obj = obj
        self.construct = construct

    # porcelain

    @classmethod
    def factory(cls, func):
        @functools.wraps(func)
        def getter(self):
            return cls(self, func)
        return cachedproperty(getter)

    def create(self):
        if not self._has:
            self._new()

    def destroy(self):
        if self._has:
            self._del()

    def toggle(self):
        if self._has:
            self._del()
        else:
            self._new()

    def _new(self):
        val = self.construct(self.obj)
        self._set(val)
        return val

    @property
    def _has(self):
        return safe_hasattr(self, '_val')

    def _get(self):
        return self._val

    def _set(self, val):
        self._val = val

    def _del(self):
        del self._val

    # use lambdas to enable overriding the _get/_set/_del methods
    # without having to redefine the 'val' property
    val = property(lambda self:      self._get(),
                   lambda self, val: self._set(val),
                   lambda self:      self._del())


# dictionary utils

def rename_key(d, name, new):
    if name in d:
        d[new] = d.pop(name)


def merged(d1, *others):
    r = d1.copy()
    for d in others:
        r.update(d)
    return r


def translate_default(d, name, old_default, new_default):
    if d[name] == old_default:
        d[name] = new_default
