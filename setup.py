from setuptools import setup, find_packages


setup(
    name='turquoise',
    version='0.1.0',
    description=(
        'A utility for performing blue-green deployments on AWS Auto Scaling '
        + 'Groups.'
    ),
    long_description=open('README.rst').read(),
    author='Theron Luhn',
    author_email='theron@luhn.com',
    url='https://github.com/luhn/turquoise',
    install_requires=[
        'boto3>=1.3.0,<2.0.0',
    ],
    packages=find_packages(),
    entry_points={
        'console_scripts': ['turquoise=turquoise:main'],
    },
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.5',
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Console',
        'License :: OSI Approved :: MIT License',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
    ],
)
