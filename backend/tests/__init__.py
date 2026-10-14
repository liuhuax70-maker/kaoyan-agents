"""测试包。

显式声明为包，让 pytest 以 ``backend`` 为根插入 sys.path，
从而既能 ``import app``，也能 ``from tests.fakes import ...``。
"""