package com.cascadeshield.inventory.service;

import com.cascadeshield.inventory.exception.InsufficientStockException;
import com.cascadeshield.inventory.exception.SkuNotFoundException;
import com.cascadeshield.inventory.model.InventoryItem;
import com.cascadeshield.inventory.model.ReserveResponse;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Inventory business logic. The store is an in-memory map — deliberately no
 * database in Week 1. Persistence (Jay's Postgres/DynamoDB-Local) plugs in
 * later; keeping it in-memory now means Service B has zero external
 * dependencies, so any fault we inject during experiments is unambiguously
 * the fault we injected, not a flaky DB.
 */
@Service
public class InventoryService {

    private final Map<String, Integer> stock = new ConcurrentHashMap<>();

    @PostConstruct
    void seed() {
        stock.put("SKU-1001", 50);
        stock.put("SKU-1002", 20);
        stock.put("SKU-1003", 0);   // intentionally out of stock for 409 testing
    }

    public InventoryItem getItem(String sku) {
        Integer available = stock.get(sku);
        if (available == null) {
            throw new SkuNotFoundException(sku);
        }
        return new InventoryItem(sku, available);
    }

    public ReserveResponse reserve(String sku, int quantity) {
        // computeIfPresent gives us atomic read-modify-write per SKU.
        Integer available = stock.get(sku);
        if (available == null) {
            throw new SkuNotFoundException(sku);
        }
        if (available < quantity) {
            throw new InsufficientStockException(sku, quantity, available);
        }
        int remaining = stock.merge(sku, -quantity, Integer::sum);
        return new ReserveResponse(sku, quantity, remaining);
    }
}
