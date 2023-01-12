class MyDemoClass:
    _foo: int = 0

    def get_foo(self, *args, **kwargs):
        return self._foo

    def set_foo(self, foo):
        self._foo = foo

    def unpatched(self, *args, **kwargs):
        return self._foo


class MyOtherClass:
    _foo: int = 0

    def foo(self, *args, **kwargs):
        return self._foo
