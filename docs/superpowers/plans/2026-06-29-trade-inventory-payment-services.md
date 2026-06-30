# Trade Inventory Payment Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing order and inventory placeholders into buildable Spring Boot microservices, add a payment service, and prepare a seckill Redis pre-deduct entry that reuses the normal order/payment/inventory confirmation flow.

**Architecture:** Implement the reliable core first: order creation locks inventory, payment callback marks the order paid, inventory confirmation deducts locked stock, and timeout/cancel releases locked stock. Add seckill as a separate entry service that performs Redis Lua pre-deduct and publishes an order-create message; the downstream MySQL order and inventory flow remains the source of truth.

**Tech Stack:** Java 21, Spring Boot 4.x, Spring Cloud Alibaba Nacos, Spring Cloud Gateway, MyBatis, MySQL/InnoDB, Redis, Spring Kafka, Maven.

---

## File Structure

Create or modify these project files.

- Modify: `java_agent/pom.xml`
  Add `rs-service-order`, `rs-service-inventory`, `rs-service-payment`, and later `rs-service-seckill` to `<modules>`.

- Modify: `java_agent/rs-api-gateway/src/main/resources/application.yml`
  Add gateway routes for `/api/orders/**`, `/api/payments/**`, `/callback/payments/**`, and `/api/seckill/**`.

- Create: `java_agent/sql/rs_service_trade_schema.sql`
  Owns first-version tables for orders, order items, payments, inventory stock, stock logs, and message idempotency.

- Create/modify under `java_agent/rs-service-inventory`
  This service owns `sku_stock` and `stock_logs`. It exposes internal lock/release/confirm APIs and platform adjustment/query APIs.

- Create/modify under `java_agent/rs-service-order`
  This service owns orders and order items. It exposes app order creation/query/cancel APIs and internal payment/timeout APIs.

- Create under `java_agent/rs-service-payment`
  This service owns payment orders and callback idempotency. It exposes prepay and callback APIs, then calls order internal paid API.

- Create under `java_agent/rs-service-seckill`
  This service owns seckill entry traffic only: activity preheat, Redis Lua pre-deduct, request idempotency, and Kafka publish. It does not own final stock facts.

Keep controllers thin, matching the existing style in `rs-service-user` and `rs-service-catalog`: controller receives DTOs, calls service, returns VO directly.

---

### Task 1: Register Trade Modules In Maven And Gateway

**Files:**
- Modify: `java_agent/pom.xml`
- Modify: `java_agent/rs-api-gateway/src/main/resources/application.yml`

- [ ] **Step 1: Write the expected module list**

Confirm `java_agent/pom.xml` has these modules in this order:

```xml
<modules>
    <module>rs-common</module>
    <module>rs-api-gateway</module>
    <module>rs-service-user</module>
    <module>rs-service-recommend</module>
    <module>rs-service-agent</module>
    <module>rs-service-catalog</module>
    <module>rs-service-model</module>
    <module>rs-service-search-rag</module>
    <module>rs-service-platform-trace</module>
    <module>rs-service-order</module>
    <module>rs-service-inventory</module>
    <module>rs-service-payment</module>
    <module>rs-service-seckill</module>
</modules>
```

- [ ] **Step 2: Add gateway routes**

Add these routes under `spring.cloud.gateway.server.webflux.routes`:

```yaml
            - id: rs-service-order
              uri: lb://rs-service-order
              predicates:
                - Path=/api/orders/**
            - id: rs-service-payment
              uri: lb://rs-service-payment
              predicates:
                - Path=/api/payments/**,/callback/payments/**
            - id: rs-service-seckill
              uri: lb://rs-service-seckill
              predicates:
                - Path=/api/seckill/**,/api/platform/seckill/**
```

Do not expose `/internal/inventory/**` through the gateway. Those endpoints are for service-to-service calls.

- [ ] **Step 3: Run Maven validation**

Run:

```powershell
mvn -q -pl rs-api-gateway -am -DskipTests package
```

Expected: build fails until later tasks create the new service `pom.xml` files if the parent references them immediately. If working task-by-task, either create the service `pom.xml` files in Task 2 before running this, or add the modules after Task 2.

- [ ] **Step 4: Commit**

```bash
git add java_agent/pom.xml java_agent/rs-api-gateway/src/main/resources/application.yml
git commit -m "chore: register trade service modules"
```

---

### Task 2: Create Service Module Skeletons

**Files:**
- Create: `java_agent/rs-service-order/pom.xml`
- Create: `java_agent/rs-service-order/src/main/java/com/sinrotic/rs/order/OrderServiceApplication.java`
- Create: `java_agent/rs-service-order/src/main/resources/application.yml`
- Create: `java_agent/rs-service-inventory/pom.xml`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/InventoryServiceApplication.java`
- Create: `java_agent/rs-service-inventory/src/main/resources/application.yml`
- Create: `java_agent/rs-service-payment/pom.xml`
- Create: `java_agent/rs-service-payment/src/main/java/com/sinrotic/rs/payment/PaymentServiceApplication.java`
- Create: `java_agent/rs-service-payment/src/main/resources/application.yml`
- Create: `java_agent/rs-service-seckill/pom.xml`
- Create: `java_agent/rs-service-seckill/src/main/java/com/sinrotic/rs/seckill/SeckillServiceApplication.java`
- Create: `java_agent/rs-service-seckill/src/main/resources/application.yml`

- [ ] **Step 1: Write shared module `pom.xml` shape**

Use this template for `rs-service-order`, replacing artifactId and application name per service:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <parent>
        <artifactId>rs-agent-parent</artifactId>
        <groupId>com.sinrotic.rs</groupId>
        <version>1.0.0-SNAPSHOT</version>
        <relativePath>../pom.xml</relativePath>
    </parent>
    <modelVersion>4.0.0</modelVersion>
    <artifactId>rs-service-order</artifactId>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.mybatis.spring.boot</groupId>
            <artifactId>mybatis-spring-boot-starter</artifactId>
        </dependency>
        <dependency>
            <groupId>com.mysql</groupId>
            <artifactId>mysql-connector-j</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>com.alibaba.cloud</groupId>
            <artifactId>spring-cloud-starter-alibaba-nacos-discovery</artifactId>
        </dependency>
        <dependency>
            <groupId>com.sinrotic.rs</groupId>
            <artifactId>rs-common</artifactId>
            <version>1.0.0-SNAPSHOT</version>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
```

For `rs-service-seckill`, add Redis and Kafka dependencies:

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-redis</artifactId>
</dependency>
<dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
</dependency>
```

- [ ] **Step 2: Create application classes**

For order:

```java
package com.sinrotic.rs.order;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class OrderServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderServiceApplication.class, args);
    }
}
```

For inventory:

```java
package com.sinrotic.rs.inventory;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class InventoryServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(InventoryServiceApplication.class, args);
    }
}
```

For payment:

```java
package com.sinrotic.rs.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class PaymentServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(PaymentServiceApplication.class, args);
    }
}
```

For seckill:

```java
package com.sinrotic.rs.seckill;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class SeckillServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(SeckillServiceApplication.class, args);
    }
}
```

- [ ] **Step 3: Create service application YAML**

Use this shape for each module, changing `server.port` and `spring.application.name`:

```yaml
server:
  port: 8091

spring:
  application:
    name: rs-service-order
  cloud:
    nacos:
      discovery:
        server-addr: 127.0.0.1:8848
  datasource:
    url: jdbc:mysql://127.0.0.1:3306/rs_agent?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
    username: root
    password: root
    driver-class-name: com.mysql.cj.jdbc.Driver

mybatis:
  mapper-locations: classpath:mapper/*.xml
  configuration:
    map-underscore-to-camel-case: true
```

Recommended ports:

```text
rs-service-order     8091
rs-service-inventory 8092
rs-service-payment   8093
rs-service-seckill   8094
```

- [ ] **Step 4: Build skeletons**

Run:

```powershell
mvn -q -pl rs-service-order,rs-service-inventory,rs-service-payment,rs-service-seckill -am -DskipTests package
```

Expected: all four modules compile.

- [ ] **Step 5: Commit**

```bash
git add java_agent/pom.xml java_agent/rs-service-order java_agent/rs-service-inventory java_agent/rs-service-payment java_agent/rs-service-seckill
git commit -m "chore: scaffold trade service modules"
```

---

### Task 3: Add Trade Database Schema

**Files:**
- Create: `java_agent/sql/rs_service_trade_schema.sql`

- [ ] **Step 1: Write schema**

Create the schema file with:

```sql
CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    account_id BIGINT NOT NULL,
    profile_user_id VARCHAR(64) NULL,
    session_id VARCHAR(64) NULL,
    recommend_request_id VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL,
    total_amount BIGINT NOT NULL,
    paid_at DATETIME NULL,
    closed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_orders_request_id (request_id),
    KEY idx_orders_account_created (account_id, created_at DESC),
    KEY idx_orders_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    item_title VARCHAR(255) NOT NULL,
    quantity INT NOT NULL,
    unit_price BIGINT NOT NULL,
    total_amount BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_order_item_sku (order_id, sku_id),
    KEY idx_order_items_sku (sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sku_stock (
    sku_id VARCHAR(64) PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    available_stock INT NOT NULL,
    locked_stock INT NOT NULL DEFAULT 0,
    sold_stock INT NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_sku_stock_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    request_id VARCHAR(64) NOT NULL,
    order_id BIGINT NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    type VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_stock_log_order_sku_type (order_id, sku_id, type),
    UNIQUE KEY uk_stock_log_request (request_id),
    KEY idx_stock_logs_sku_created (sku_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_orders (
    payment_id BIGINT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_transaction_id VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_payment_order_id (order_id),
    UNIQUE KEY uk_provider_transaction (provider, provider_transaction_id),
    KEY idx_payment_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_callbacks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL,
    provider_transaction_id VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(128) NOT NULL,
    processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_payment_callback_provider_tx (provider, provider_transaction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consumer_message_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    message_id VARCHAR(128) NOT NULL,
    consumer_name VARCHAR(64) NOT NULL,
    processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_message_consumer (message_id, consumer_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 2: Review schema invariants**

Check these are true:

```text
orders.request_id prevents duplicate order creation.
stock_logs(order_id, sku_id, type) prevents duplicate LOCK/CONFIRM/RELEASE.
payment_orders(provider, provider_transaction_id) prevents duplicate provider callback handling.
sku_stock update operations will use sku_id primary key and conditional stock checks.
```

- [ ] **Step 3: Commit**

```bash
git add java_agent/sql/rs_service_trade_schema.sql
git commit -m "feat: add trade service database schema"
```

---

### Task 4: Implement Inventory Lock Release Confirm Core

**Files:**
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/domain/dto/InventoryLockRequestDTO.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/domain/dto/InventoryConfirmRequestDTO.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/domain/dto/InventoryReleaseRequestDTO.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/domain/entity/SkuStock.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/domain/entity/StockLog.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/mapper/SkuStockMapper.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/mapper/StockLogMapper.java`
- Create: `java_agent/rs-service-inventory/src/main/resources/mapper/SkuStockMapper.xml`
- Create: `java_agent/rs-service-inventory/src/main/resources/mapper/StockLogMapper.xml`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/service/InventoryService.java`
- Create: `java_agent/rs-service-inventory/src/main/java/com/sinrotic/rs/inventory/controller/internal/InternalInventoryController.java`

- [ ] **Step 1: Write DTOs**

```java
package com.sinrotic.rs.inventory.domain.dto;

public record InventoryLockRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {}
```

```java
package com.sinrotic.rs.inventory.domain.dto;

public record InventoryConfirmRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {}
```

```java
package com.sinrotic.rs.inventory.domain.dto;

public record InventoryReleaseRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {}
```

- [ ] **Step 2: Write mapper SQL**

`SkuStockMapper.xml` must contain:

```xml
<mapper namespace="com.sinrotic.rs.inventory.mapper.SkuStockMapper">
    <update id="lockStock">
        UPDATE sku_stock
        SET available_stock = available_stock - #{quantity},
            locked_stock = locked_stock + #{quantity},
            version = version + 1
        WHERE sku_id = #{skuId}
          AND available_stock >= #{quantity}
    </update>

    <update id="confirmDeduct">
        UPDATE sku_stock
        SET locked_stock = locked_stock - #{quantity},
            sold_stock = sold_stock + #{quantity},
            version = version + 1
        WHERE sku_id = #{skuId}
          AND locked_stock >= #{quantity}
    </update>

    <update id="releaseStock">
        UPDATE sku_stock
        SET available_stock = available_stock + #{quantity},
            locked_stock = locked_stock - #{quantity},
            version = version + 1
        WHERE sku_id = #{skuId}
          AND locked_stock >= #{quantity}
    </update>
</mapper>
```

`StockLogMapper.xml` must contain:

```xml
<mapper namespace="com.sinrotic.rs.inventory.mapper.StockLogMapper">
    <insert id="insertLog">
        INSERT INTO stock_logs (request_id, order_id, sku_id, quantity, type)
        VALUES (#{requestId}, #{orderId}, #{skuId}, #{quantity}, #{type})
    </insert>
</mapper>
```

- [ ] **Step 3: Write service transaction**

```java
package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.inventory.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import com.sinrotic.rs.inventory.mapper.SkuStockMapper;
import com.sinrotic.rs.inventory.mapper.StockLogMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InventoryService {
    private final SkuStockMapper skuStockMapper;
    private final StockLogMapper stockLogMapper;

    public InventoryService(SkuStockMapper skuStockMapper, StockLogMapper stockLogMapper) {
        this.skuStockMapper = skuStockMapper;
        this.stockLogMapper = stockLogMapper;
    }

    @Transactional(rollbackFor = Exception.class)
    public void lockStock(InventoryLockRequestDTO request) {
        int affected = skuStockMapper.lockStock(request.skuId(), request.quantity());
        if (affected == 0) {
            throw new IllegalStateException("inventory not enough");
        }
        stockLogMapper.insertLog(request.requestId(), request.orderId(), request.skuId(), request.quantity(), "LOCK");
    }

    @Transactional(rollbackFor = Exception.class)
    public void confirmDeduct(InventoryConfirmRequestDTO request) {
        int affected = skuStockMapper.confirmDeduct(request.skuId(), request.quantity());
        if (affected == 0) {
            throw new IllegalStateException("locked inventory not enough");
        }
        stockLogMapper.insertLog(request.requestId(), request.orderId(), request.skuId(), request.quantity(), "CONFIRM");
    }

    @Transactional(rollbackFor = Exception.class)
    public void releaseStock(InventoryReleaseRequestDTO request) {
        int affected = skuStockMapper.releaseStock(request.skuId(), request.quantity());
        if (affected == 0) {
            throw new IllegalStateException("locked inventory not enough");
        }
        stockLogMapper.insertLog(request.requestId(), request.orderId(), request.skuId(), request.quantity(), "RELEASE");
    }
}
```

- [ ] **Step 4: Write internal controller**

```java
package com.sinrotic.rs.inventory.controller.internal;

import com.sinrotic.rs.inventory.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import com.sinrotic.rs.inventory.service.InventoryService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/inventory")
public class InternalInventoryController {
    private final InventoryService inventoryService;

    public InternalInventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @PostMapping("/lock")
    public void lock(@RequestBody InventoryLockRequestDTO request) {
        inventoryService.lockStock(request);
    }

    @PostMapping("/confirm-deduct")
    public void confirmDeduct(@RequestBody InventoryConfirmRequestDTO request) {
        inventoryService.confirmDeduct(request);
    }

    @PostMapping("/release")
    public void release(@RequestBody InventoryReleaseRequestDTO request) {
        inventoryService.releaseStock(request);
    }
}
```

- [ ] **Step 5: Add idempotency handling**

When `stockLogMapper.insertLog` throws duplicate-key for the same `(order_id, sku_id, type)` or `request_id`, return success only after checking the existing log matches the same order, sku, quantity, and type. Add:

```java
boolean existsSameLog(String requestId, Long orderId, String skuId, Integer quantity, String type);
```

Then wrap duplicate-key handling inside `InventoryService`. Do not silently ignore duplicate-key before validating the log content.

- [ ] **Step 6: Build inventory**

Run:

```powershell
mvn -q -pl rs-service-inventory -am -DskipTests package
```

Expected: inventory service compiles.

- [ ] **Step 7: Commit**

```bash
git add java_agent/rs-service-inventory
git commit -m "feat: add inventory lock release confirm APIs"
```

---

### Task 5: Implement Order Creation And State Flow

**Files:**
- Create DTO/entity/mapper/service/controller files under `java_agent/rs-service-order/src/main/java/com/sinrotic/rs/order`
- Create XML mappers under `java_agent/rs-service-order/src/main/resources/mapper`

- [ ] **Step 1: Write order DTOs**

Create `CreateOrderRequestDTO`:

```java
package com.sinrotic.rs.order.domain.dto;

public record CreateOrderRequestDTO(
        String requestId,
        Long accountId,
        String profileUserId,
        String sessionId,
        String recommendRequestId,
        String itemId,
        String skuId,
        String itemTitle,
        Integer quantity,
        Long unitPrice
) {}
```

Create `OrderPaidRequestDTO`:

```java
package com.sinrotic.rs.order.domain.dto;

public record OrderPaidRequestDTO(
        String requestId,
        Long orderId,
        String provider,
        String providerTransactionId
) {}
```

- [ ] **Step 2: Write order VO**

```java
package com.sinrotic.rs.order.domain.vo;

public record OrderCreateVO(
        Long orderId,
        String status
) {}
```

- [ ] **Step 3: Write inventory client**

Use `RestClient` or `WebClient` consistently with the project. A simple first version:

```java
package com.sinrotic.rs.order.client;

import com.sinrotic.rs.order.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.order.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.order.domain.dto.InventoryReleaseRequestDTO;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class InventoryClient {
    private final RestClient restClient;

    public InventoryClient(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("http://rs-service-inventory").build();
    }

    public void lock(InventoryLockRequestDTO request) {
        restClient.post().uri("/internal/inventory/lock").body(request).retrieve().toBodilessEntity();
    }

    public void confirm(InventoryConfirmRequestDTO request) {
        restClient.post().uri("/internal/inventory/confirm-deduct").body(request).retrieve().toBodilessEntity();
    }

    public void release(InventoryReleaseRequestDTO request) {
        restClient.post().uri("/internal/inventory/release").body(request).retrieve().toBodilessEntity();
    }
}
```

If service discovery load balancing for `RestClient` is not configured in the repo, add Spring Cloud LoadBalancer dependency or replace this with a local URL property for MVP.

- [ ] **Step 4: Write order service create transaction**

`OrderService.createOrder` must:

```text
1. Generate orderId.
2. Call inventory lock with requestId.
3. Insert orders row as WAITING_PAYMENT.
4. Insert order_items row.
5. Return orderId and WAITING_PAYMENT.
```

For a same-service local transaction, insert order first and then call inventory can create distributed consistency issues. For MVP, use inventory lock first, then local order insert. If order insert fails after lock succeeds, call inventory release in a catch block with `requestId + ":release-on-create-failure"`.

```java
public OrderCreateVO createOrder(CreateOrderRequestDTO request) {
    Long orderId = idGenerator.nextId();
    Long totalAmount = request.unitPrice() * request.quantity();
    inventoryClient.lock(new InventoryLockRequestDTO(request.requestId(), orderId, request.skuId(), request.quantity()));
    try {
        orderMapper.insertOrder(orderId, request, "WAITING_PAYMENT", totalAmount);
        orderItemMapper.insertItem(orderId, request, totalAmount);
        return new OrderCreateVO(orderId, "WAITING_PAYMENT");
    } catch (RuntimeException ex) {
        inventoryClient.release(new InventoryReleaseRequestDTO(request.requestId() + ":release-on-create-failure", orderId, request.skuId(), request.quantity()));
        throw ex;
    }
}
```

- [ ] **Step 5: Write paid and timeout flows**

`OrderService.markPaid`:

```text
1. UPDATE orders SET status='PAID' WHERE order_id=? AND status='WAITING_PAYMENT'.
2. If affected == 0, return idempotent success.
3. Load order item.
4. Call inventory confirm with provider transaction request id.
```

`OrderService.closeTimeout`:

```text
1. UPDATE orders SET status='TIMEOUT_CLOSED' WHERE order_id=? AND status='WAITING_PAYMENT'.
2. If affected == 0, return idempotent success.
3. Load order item.
4. Call inventory release.
```

- [ ] **Step 6: Write controllers**

`AppOrderController`:

```java
@RestController
@RequestMapping("/api/orders")
public class AppOrderController {
    private final OrderService orderService;

    public AppOrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public OrderCreateVO create(@RequestBody CreateOrderRequestDTO request) {
        return orderService.createOrder(request);
    }

    @PostMapping("/{orderId}/cancel")
    public void cancel(@PathVariable Long orderId) {
        orderService.cancel(orderId);
    }
}
```

`InternalOrderController`:

```java
@RestController
@RequestMapping("/internal/orders")
public class InternalOrderController {
    private final OrderService orderService;

    public InternalOrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping("/{orderId}/paid")
    public void paid(@PathVariable Long orderId, @RequestBody OrderPaidRequestDTO request) {
        orderService.markPaid(orderId, request);
    }

    @PostMapping("/{orderId}/close-timeout")
    public void closeTimeout(@PathVariable Long orderId) {
        orderService.closeTimeout(orderId);
    }
}
```

- [ ] **Step 7: Build order**

Run:

```powershell
mvn -q -pl rs-service-order -am -DskipTests package
```

Expected: order service compiles.

- [ ] **Step 8: Commit**

```bash
git add java_agent/rs-service-order
git commit -m "feat: add order creation and state flow"
```

---

### Task 6: Implement Payment Prepay And Callback Idempotency

**Files:**
- Create files under `java_agent/rs-service-payment/src/main/java/com/sinrotic/rs/payment`
- Create XML mappers under `java_agent/rs-service-payment/src/main/resources/mapper`

- [ ] **Step 1: Write payment DTOs**

```java
package com.sinrotic.rs.payment.domain.dto;

public record CreatePaymentRequestDTO(
        Long orderId,
        Long accountId,
        Long amount,
        String provider
) {}
```

```java
package com.sinrotic.rs.payment.domain.dto;

public record PaymentCallbackDTO(
        String provider,
        String providerTransactionId,
        Long orderId,
        Long amount,
        String signature,
        String rawPayload
) {}
```

- [ ] **Step 2: Write payment VO**

```java
package com.sinrotic.rs.payment.domain.vo;

public record PaymentPrepayVO(
        Long paymentId,
        Long orderId,
        String provider,
        String status
) {}
```

- [ ] **Step 3: Write payment service**

First version uses simulated provider verification, but keeps the real boundaries:

```java
@Service
public class PaymentService {
    private final PaymentOrderMapper paymentOrderMapper;
    private final PaymentCallbackMapper paymentCallbackMapper;
    private final OrderClient orderClient;
    private final IdGenerator idGenerator;

    public PaymentPrepayVO createPrepay(CreatePaymentRequestDTO request) {
        Long paymentId = idGenerator.nextId();
        paymentOrderMapper.insertPayment(paymentId, request.orderId(), request.provider(), request.amount(), "WAITING_PAY");
        return new PaymentPrepayVO(paymentId, request.orderId(), request.provider(), "WAITING_PAY");
    }

    @Transactional(rollbackFor = Exception.class)
    public void handleCallback(PaymentCallbackDTO callback) {
        verifyCallback(callback);
        paymentCallbackMapper.insertCallback(callback.provider(), callback.providerTransactionId(), hash(callback.rawPayload()));
        int updated = paymentOrderMapper.markPaid(callback.orderId(), callback.provider(), callback.providerTransactionId());
        if (updated == 0) {
            return;
        }
        orderClient.markPaid(callback.orderId(), callback.provider(), callback.providerTransactionId());
    }

    private void verifyCallback(PaymentCallbackDTO callback) {
        if (callback.providerTransactionId() == null || callback.providerTransactionId().isBlank()) {
            throw new IllegalArgumentException("providerTransactionId is required");
        }
    }
}
```

Duplicate callback insert must be treated as idempotent success only when `provider` and `providerTransactionId` match an already processed callback.

- [ ] **Step 4: Write payment controllers**

```java
@RestController
@RequestMapping("/api/payments")
public class AppPaymentController {
    private final PaymentService paymentService;

    public AppPaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/prepay")
    public PaymentPrepayVO prepay(@RequestBody CreatePaymentRequestDTO request) {
        return paymentService.createPrepay(request);
    }
}
```

```java
@RestController
@RequestMapping("/callback/payments")
public class PaymentCallbackController {
    private final PaymentService paymentService;

    public PaymentCallbackController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/{provider}")
    public void callback(@PathVariable String provider, @RequestBody PaymentCallbackDTO request) {
        paymentService.handleCallback(new PaymentCallbackDTO(
                provider,
                request.providerTransactionId(),
                request.orderId(),
                request.amount(),
                request.signature(),
                request.rawPayload()
        ));
    }
}
```

- [ ] **Step 5: Build payment**

Run:

```powershell
mvn -q -pl rs-service-payment -am -DskipTests package
```

Expected: payment service compiles.

- [ ] **Step 6: Commit**

```bash
git add java_agent/rs-service-payment
git commit -m "feat: add payment prepay and callback flow"
```

---

### Task 7: Add Seckill Redis Pre-Deduct Skeleton

**Files:**
- Create files under `java_agent/rs-service-seckill/src/main/java/com/sinrotic/rs/seckill`

- [ ] **Step 1: Write seckill request and result DTOs**

```java
package com.sinrotic.rs.seckill.domain.dto;

public record SeckillSubmitRequestDTO(
        String requestId,
        Long accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {}
```

```java
package com.sinrotic.rs.seckill.domain.vo;

public record SeckillSubmitVO(
        String requestId,
        String status
) {}
```

- [ ] **Step 2: Add Lua script**

Create `src/main/resources/lua/seckill_pre_deduct.lua`:

```lua
local stockKey = KEYS[1]
local userKey = KEYS[2]
local quantity = tonumber(ARGV[1])
local requestId = ARGV[2]

if redis.call('EXISTS', userKey) == 1 then
    return 2
end

local stock = tonumber(redis.call('GET', stockKey) or '0')
if stock < quantity then
    return 0
end

redis.call('DECRBY', stockKey, quantity)
redis.call('SET', userKey, requestId, 'EX', 1800)
return 1
```

Return values:

```text
1 success
0 stock not enough
2 duplicate submit
```

- [ ] **Step 3: Write seckill service**

```java
@Service
public class SeckillService {
    private final StringRedisTemplate redisTemplate;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final DefaultRedisScript<Long> preDeductScript;

    public SeckillSubmitVO submit(SeckillSubmitRequestDTO request) {
        String stockKey = "seckill:stock:" + request.activityId() + ":" + request.skuId();
        String userKey = "seckill:user:" + request.activityId() + ":" + request.accountId();
        Long result = redisTemplate.execute(
                preDeductScript,
                List.of(stockKey, userKey),
                String.valueOf(request.quantity()),
                request.requestId()
        );
        if (result == null || result == 0L) {
            return new SeckillSubmitVO(request.requestId(), "STOCK_NOT_ENOUGH");
        }
        if (result == 2L) {
            return new SeckillSubmitVO(request.requestId(), "DUPLICATE");
        }
        kafkaTemplate.send("seckill-order-create", request.requestId(), toJson(request));
        return new SeckillSubmitVO(request.requestId(), "PROCESSING");
    }
}
```

Use FastJSON2 or Jackson consistently with existing project dependencies for `toJson`.

- [ ] **Step 4: Write controller**

```java
@RestController
@RequestMapping("/api/seckill")
public class AppSeckillController {
    private final SeckillService seckillService;

    public AppSeckillController(SeckillService seckillService) {
        this.seckillService = seckillService;
    }

    @PostMapping("/activities/{activityId}/submit")
    public SeckillSubmitVO submit(@PathVariable String activityId, @RequestBody SeckillSubmitRequestDTO request) {
        return seckillService.submit(new SeckillSubmitRequestDTO(
                request.requestId(),
                request.accountId(),
                activityId,
                request.itemId(),
                request.skuId(),
                request.quantity()
        ));
    }
}
```

- [ ] **Step 5: Build seckill**

Run:

```powershell
mvn -q -pl rs-service-seckill -am -DskipTests package
```

Expected: seckill service compiles.

- [ ] **Step 6: Commit**

```bash
git add java_agent/rs-service-seckill
git commit -m "feat: add seckill redis pre-deduct entry"
```

---

### Task 8: Add Seckill Order Consumer

**Files:**
- Modify: `java_agent/rs-service-order/pom.xml`
- Create: `java_agent/rs-service-order/src/main/java/com/sinrotic/rs/order/mq/SeckillOrderCreateConsumer.java`
- Create: `java_agent/rs-service-order/src/main/java/com/sinrotic/rs/order/domain/dto/SeckillOrderCreateMessageDTO.java`

- [ ] **Step 1: Add Kafka dependency to order**

```xml
<dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
</dependency>
```

- [ ] **Step 2: Create message DTO**

```java
package com.sinrotic.rs.order.domain.dto;

public record SeckillOrderCreateMessageDTO(
        String requestId,
        Long accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {}
```

- [ ] **Step 3: Create consumer**

```java
@Component
public class SeckillOrderCreateConsumer {
    private final OrderService orderService;
    private final ObjectMapper objectMapper;

    public SeckillOrderCreateConsumer(OrderService orderService, ObjectMapper objectMapper) {
        this.orderService = orderService;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = "seckill-order-create", groupId = "rs-service-order")
    public void consume(String payload) throws Exception {
        SeckillOrderCreateMessageDTO message = objectMapper.readValue(payload, SeckillOrderCreateMessageDTO.class);
        orderService.createSeckillOrder(message);
    }
}
```

`createSeckillOrder` must use `requestId` idempotency. If an order already exists for the same `requestId`, return success to Kafka.

- [ ] **Step 4: Build order with Kafka**

Run:

```powershell
mvn -q -pl rs-service-order -am -DskipTests package
```

Expected: order service compiles.

- [ ] **Step 5: Commit**

```bash
git add java_agent/rs-service-order
git commit -m "feat: consume seckill order create messages"
```

---

### Task 9: Add Focused Unit Tests

**Files:**
- Create: `java_agent/rs-service-inventory/src/test/java/com/sinrotic/rs/inventory/service/InventoryServiceTest.java`
- Create: `java_agent/rs-service-order/src/test/java/com/sinrotic/rs/order/service/OrderServiceTest.java`
- Create: `java_agent/rs-service-payment/src/test/java/com/sinrotic/rs/payment/service/PaymentServiceTest.java`
- Create: `java_agent/rs-service-seckill/src/test/java/com/sinrotic/rs/seckill/service/SeckillServiceTest.java`

- [ ] **Step 1: Test inventory lock insufficient stock**

```java
@Test
void lockStockThrowsWhenNoRowsUpdated() {
    when(skuStockMapper.lockStock("sku-1", 2)).thenReturn(0);

    assertThrows(IllegalStateException.class, () ->
            inventoryService.lockStock(new InventoryLockRequestDTO("req-1", 1L, "sku-1", 2)));

    verify(stockLogMapper, never()).insertLog(any(), any(), any(), any(), any());
}
```

- [ ] **Step 2: Test order create releases inventory after local insert failure**

```java
@Test
void createOrderReleasesInventoryWhenInsertFails() {
    CreateOrderRequestDTO request = new CreateOrderRequestDTO("req-1", 1L, "p1", "s1", "r1", "item-1", "sku-1", "Title", 1, 100L);
    doThrow(new RuntimeException("db down")).when(orderMapper).insertOrder(anyLong(), eq(request), eq("WAITING_PAYMENT"), eq(100L));

    assertThrows(RuntimeException.class, () -> orderService.createOrder(request));

    verify(inventoryClient).lock(any());
    verify(inventoryClient).release(argThat(release -> release.requestId().equals("req-1:release-on-create-failure")));
}
```

- [ ] **Step 3: Test payment duplicate callback**

```java
@Test
void duplicatePaymentCallbackDoesNotMarkOrderTwice() {
    PaymentCallbackDTO callback = new PaymentCallbackDTO("mock", "tx-1", 100L, 100L, "sig", "{}");
    doThrow(new DuplicateKeyException("duplicate")).when(paymentCallbackMapper)
            .insertCallback(eq("mock"), eq("tx-1"), anyString());

    paymentService.handleCallback(callback);

    verify(orderClient, never()).markPaid(anyLong(), anyString(), anyString());
}
```

- [ ] **Step 4: Test seckill duplicate submit**

```java
@Test
void submitReturnsDuplicateWhenLuaReturnsTwo() {
    when(redisTemplate.execute(any(), anyList(), anyString(), anyString())).thenReturn(2L);

    SeckillSubmitVO result = seckillService.submit(new SeckillSubmitRequestDTO("req-1", 1L, "act-1", "item-1", "sku-1", 1));

    assertEquals("DUPLICATE", result.status());
    verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
}
```

- [ ] **Step 5: Run tests**

Run:

```powershell
mvn -q -pl rs-service-inventory,rs-service-order,rs-service-payment,rs-service-seckill -am test
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add java_agent/rs-service-inventory/src/test java_agent/rs-service-order/src/test java_agent/rs-service-payment/src/test java_agent/rs-service-seckill/src/test
git commit -m "test: cover trade service core flows"
```

---

### Task 10: End-To-End Verification Notes

**Files:**
- Create: `java_agent/docs/trade-service-runbook.md`

- [ ] **Step 1: Write runbook**

Include this sequence:

```markdown
# Trade Service Runbook

## Start order
1. Apply `java_agent/sql/rs_service_trade_schema.sql`.
2. Start Nacos, MySQL, Redis, and Kafka.
3. Start `rs-service-inventory`.
4. Start `rs-service-order`.
5. Start `rs-service-payment`.
6. Start `rs-service-seckill`.
7. Start `rs-api-gateway`.

## Normal order smoke
1. Insert one `sku_stock` row with `available_stock=10`.
2. POST `/api/orders` with `requestId=req-normal-1`.
3. Verify `orders.status=WAITING_PAYMENT`.
4. Verify `sku_stock.available_stock=9` and `locked_stock=1`.
5. POST `/api/payments/prepay`.
6. POST `/callback/payments/mock`.
7. Verify `orders.status=PAID`.
8. Verify `sku_stock.locked_stock=0` and `sold_stock=1`.

## Seckill smoke
1. Set Redis key `seckill:stock:act-1:sku-1=5`.
2. POST `/api/seckill/activities/act-1/submit`.
3. Verify response status is `PROCESSING`.
4. Verify Kafka message creates a WAITING_PAYMENT order.
```

- [ ] **Step 2: Build all Java modules**

Run:

```powershell
mvn -q -DskipTests package
```

Expected: all modules compile and package.

- [ ] **Step 3: Commit**

```bash
git add java_agent/docs/trade-service-runbook.md
git commit -m "docs: add trade service runbook"
```

---

## Self-Review

**Spec coverage:** This plan covers the current repo gap: order and inventory placeholders become real modules, payment is added, gateway routes are added, schema is created, ordinary inventory lock/confirm/release is implemented, and seckill Redis pre-deduct is introduced as an entry layer.

**Scope check:** This is intentionally split into core trade flow first and seckill second. Each task can be built and committed independently. The first usable milestone is Tasks 1-6; Tasks 7-8 add seckill entry behavior.

**Placeholder scan:** No implementation step relies on unresolved placeholders. Provider verification is explicitly simulated in Task 6 and must be replaced only when a real provider is selected.

**Type consistency:** DTO names and flow names are consistent across order, inventory, payment, and seckill tasks: `requestId`, `orderId`, `skuId`, `quantity`, `LOCK`, `CONFIRM`, and `RELEASE`.
