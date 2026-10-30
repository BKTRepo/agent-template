# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .example_view import example_category, example_product

example_category_router = APIRouter()
example_product_router = APIRouter()

example_category_router.include_router(example_category)
example_product_router.include_router(example_product)
