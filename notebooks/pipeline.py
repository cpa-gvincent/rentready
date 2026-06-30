# Databricks notebook source
# RentReady DLT Pipeline — imports all layer modules to register tables.

import sys
sys.path.insert(0, __file__.rsplit("/", 3)[0])

import src.pipelines.bronze    # bronze_listings (streaming)
import src.pipelines.silver    # silver_listings, silver_value_estimates
import src.pipelines.silver_ml # silver_ml_features
import src.pipelines.gold      # gold_value_triangulation, gold_deal_screen
