package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.session-persistence")
public class AgentSessionPersistenceProperties {

    private boolean enabled = false;

    private String schemaVersion = "agent_session_v1";

    private Scylla scylla = new Scylla();

    private Mysql mysql = new Mysql();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getSchemaVersion() {
        return schemaVersion;
    }

    public void setSchemaVersion(String schemaVersion) {
        this.schemaVersion = schemaVersion;
    }

    public Scylla getScylla() {
        return scylla;
    }

    public void setScylla(Scylla scylla) {
        this.scylla = scylla;
    }

    public Mysql getMysql() {
        return mysql;
    }

    public void setMysql(Mysql mysql) {
        this.mysql = mysql;
    }

    public static class Scylla {

        private String host = "127.0.0.1";

        private int port = 19042;

        private String localDatacenter = "datacenter1";

        private String keyspace = "rs_agent";

        public String getHost() {
            return host;
        }

        public void setHost(String host) {
            this.host = host;
        }

        public int getPort() {
            return port;
        }

        public void setPort(int port) {
            this.port = port;
        }

        public String getLocalDatacenter() {
            return localDatacenter;
        }

        public void setLocalDatacenter(String localDatacenter) {
            this.localDatacenter = localDatacenter;
        }

        public String getKeyspace() {
            return keyspace;
        }

        public void setKeyspace(String keyspace) {
            this.keyspace = keyspace;
        }
    }

    public static class Mysql {

        private String jdbcUrl = "jdbc:mysql://127.0.0.1:13306/rs_agent?useUnicode=true&characterEncoding=utf8&useSSL=false&serverTimezone=Asia/Shanghai";

        private String username = "rs_agent";

        private String password = "rs_agent_dev_password";

        private int maximumPoolSize = 8;

        private int minimumIdle = 2;

        private long connectionTimeoutMs = 3000;

        public int getMaximumPoolSize() {
            return maximumPoolSize;
        }

        public void setMaximumPoolSize(int maximumPoolSize) {
            this.maximumPoolSize = maximumPoolSize;
        }

        public int getMinimumIdle() {
            return minimumIdle;
        }

        public void setMinimumIdle(int minimumIdle) {
            this.minimumIdle = minimumIdle;
        }

        public long getConnectionTimeoutMs() {
            return connectionTimeoutMs;
        }

        public void setConnectionTimeoutMs(long connectionTimeoutMs) {
            this.connectionTimeoutMs = connectionTimeoutMs;
        }

        public String getJdbcUrl() {
            return jdbcUrl;
        }

        public void setJdbcUrl(String jdbcUrl) {
            this.jdbcUrl = jdbcUrl;
        }

        public String getUsername() {
            return username;
        }

        public void setUsername(String username) {
            this.username = username;
        }

        public String getPassword() {
            return password;
        }

        public void setPassword(String password) {
            this.password = password;
        }
    }
}
