def test_package_imports():
    import gryag

    assert isinstance(gryag.__version__, str)
