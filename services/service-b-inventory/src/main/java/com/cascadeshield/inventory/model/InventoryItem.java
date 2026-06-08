package com.cascadeshield.inventory.model;

/** A single stock-keeping unit and how many units are on hand. */
public record InventoryItem(String sku, int available) {}
