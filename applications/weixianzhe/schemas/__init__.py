# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : __init__.py
@DateTime: 2025/4/28 18:07
"""
from applications.example.schemas.example_schema import (
    CategoryBase,
    CategoryCreate,
    CategoryUpdate,
    CategorySelect,
    ProductBase,
    ProductCreate,
    ProductUpdate,
    ProductSelect,
    BatchCreateProducts,
    BatchUpdateProducts,
    TransferStock,
)

__all__ = [
    "CategoryBase",
    "CategoryCreate",
    "CategoryUpdate",
    "CategorySelect",
    "ProductBase",
    "ProductCreate",
    "ProductUpdate",
    "ProductSelect",
    "BatchCreateProducts",
    "BatchUpdateProducts",
    "TransferStock",
]
