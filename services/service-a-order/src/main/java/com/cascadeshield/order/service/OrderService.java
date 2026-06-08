package com.cascadeshield.order.service;

import com.cascadeshield.order.client.InventoryClient;
import com.cascadeshield.order.model.OrderRequest;
import com.cascadeshield.order.model.OrderResponse;
import com.cascadeshield.order.model.ReserveResponse;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
public class OrderService {

    private final InventoryClient inventoryClient;

    public OrderService(InventoryClient inventoryClient) {
        this.inventoryClient = inventoryClient;
    }

    /**
     * Place an order: reserve stock in Service B, then confirm. If the
     * reservation hop fails, InventoryClient throws and the order never
     * reaches CONFIRMED — the failure propagates up as a 503.
     */
    public OrderResponse placeOrder(OrderRequest request) {
        ReserveResponse reservation = inventoryClient.reserve(request.sku(), request.quantity());
        String orderId = "ORD-" + UUID.randomUUID().toString().substring(0, 8);
        return new OrderResponse(orderId, reservation.sku(), reservation.reserved(), "CONFIRMED");
    }
}
