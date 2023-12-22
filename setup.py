import setuptools, pyncm

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="librespot-dl",
    version=pyncm.__version__,
    author="greats3an",
    author_email="greats3an@gmail.com",
    description="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/mos9527/librespot-dl",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    install_requires=["librespot"],
    entry_points={"console_scripts": ["pyncm=pyncm.__main__:__main__"]},
    python_requires=">=3.8",
)
