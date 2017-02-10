import doctest
result = doctest.testfile('README.rst', optionflags=doctest.NORMALIZE_WHITESPACE|doctest.ELLIPSIS)
if not result[0]:
    print("test ok")
