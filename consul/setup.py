from setuptools import setup, find_packages


def parse_requirements(file):
    required = []
    with open(file) as f:
        for req in f.read().splitlines():
            if not req.strip().startswith('#'):
                required.append(req)
    return required


version = '0.1'
requires = parse_requirements('requirements.txt')
tests_requires = parse_requirements('requirements.tests.txt')

setup(
    name='consul-watcher-deployer',
    version=version,
    description="consul-watcher-deployer is an event handler for consul watch "
                "to deploy containers",
    long_description="""This package allow to deploy / migrate / move /
        destruct services defined in a docker-compose file.
    """,
    classifiers=[],
    author='Christophe Combelles',
    author_email='ccomb@anybox.fr',
    url='https://github.com/mlfmonde/cluster',
    license='MIT',
    packages=find_packages(
        exclude=['ez_setup', 'examples', 'tests']
    ),
    include_package_data=True,
    zip_safe=False,
    namespace_packages=['consul_watcher_deployer'],
    install_requires=requires,
    tests_require=requires + tests_requires,
    entry_points="""
    [console_scripts]
    handler=consul_watcher_deployer.handler:deploy_handler
    """,
)
