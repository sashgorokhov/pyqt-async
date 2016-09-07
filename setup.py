from distutils.core import setup

with open('README.rst') as file:
    long_description = file.read()

setup(
    name='pyqt-async',
    version='0.1',
    py_modules=['pyqt_async'],
    url='https://github.com/sashgorokhov/pyqt-async',
    download_url='https://github.com/sashgorokhov/pyqt-async/archive/master.zip',
    keywords=['pyqt', 'pyqt5', 'pyqt4', 'async'],
    license='MIT License',
    author='sashgorokhov',
    author_email='sashgorokhov@gmail.com',
    description='Asynchronous tools for PyQt apps',
    long_description=long_description,
)
