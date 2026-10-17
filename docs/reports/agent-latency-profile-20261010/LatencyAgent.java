package rs.profile;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.ConcurrentHashMap;
import java.io.InputStream;
import jdk.internal.org.objectweb.asm.*;
import jdk.internal.org.objectweb.asm.commons.AdviceAdapter;

/** 仅用于隔离评测的 Java Agent；不采集参数、SQL、身份或回答内容。 */
public final class LatencyAgent {
    private static final ThreadLocal<Trace> CURRENT = new ThreadLocal<>();
    private static final AtomicLong IDS = new AtomicLong();
    private static final String SELF = "rs/profile/LatencyAgent";

    public static void premain(String args, Instrumentation instrumentation) {
        instrumentation.addTransformer(new ClassFileTransformer() {
            @Override public byte[] transform(ClassLoader loader, String name, Class<?> redefined,
                    ProtectionDomain domain, byte[] bytes) {
                if (name == null || !selectedClass(name)) return null;
                try {
                    ClassReader reader = new ClassReader(bytes);
                    Map<String, Hierarchy> hierarchy = new HashMap<>();
                    hierarchy.put(name, new Hierarchy(reader.getSuperName(), reader.getInterfaces(), reader.getAccess()));
                    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS) {
                        @Override protected String getCommonSuperClass(String a, String b) {
                            // 读取 class 资源而非加载 class，防止重入转换导致 JDBC 类漏计。
                            if (a.equals(b)) return a;
                            if (a.startsWith("[") && b.startsWith("[") && a.startsWith("[L") && b.startsWith("[L"))
                                return "[L" + getCommonSuperClass(a.substring(2, a.length() - 1), b.substring(2, b.length() - 1)) + ";";
                            if (a.startsWith("[") || b.startsWith("[")) return "java/lang/Object";
                            if (assignable(a, b, loader, hierarchy)) return a;
                            if (assignable(b, a, loader, hierarchy)) return b;
                            Hierarchy x = metadata(a, loader, hierarchy), y = metadata(b, loader, hierarchy);
                            if ((x.access & Opcodes.ACC_INTERFACE) != 0 || (y.access & Opcodes.ACC_INTERFACE) != 0)
                                return "java/lang/Object";
                            do { a = metadata(a, loader, hierarchy).parent; }
                            while (a != null && !assignable(a, b, loader, hierarchy));
                            return a == null ? "java/lang/Object" : a;
                        }
                    };
                    reader.accept(new ClassVisitor(Opcodes.ASM8, writer) {
                        @Override public MethodVisitor visitMethod(int access, String method, String descriptor,
                                String signature, String[] exceptions) {
                            MethodVisitor delegate = super.visitMethod(access, method, descriptor, signature, exceptions);
                            if ((access & (Opcodes.ACC_ABSTRACT | Opcodes.ACC_NATIVE | Opcodes.ACC_SYNTHETIC)) != 0
                                    || method.startsWith("<") || !selectedMethod(name, method)) return delegate;
                            return new AdviceAdapter(Opcodes.ASM8, delegate, access, method, descriptor) {
                                int token;
                                final Label begin = new Label(), end = new Label(), handler = new Label();
                                @Override protected void onMethodEnter() {
                                    visitLdcInsn(name.substring(name.lastIndexOf('/') + 1) + "." + method);
                                    push(root(name, method));
                                    visitMethodInsn(INVOKESTATIC, SELF, "enter", "(Ljava/lang/String;Z)Ljava/lang/Object;", false);
                                    token = newLocal(Type.getType(Object.class)); storeLocal(token); visitLabel(begin);
                                }
                                void close(boolean failed) {
                                    loadLocal(token); push(failed);
                                    visitMethodInsn(INVOKESTATIC, SELF, "leave", "(Ljava/lang/Object;Z)V", false);
                                }
                                @Override protected void onMethodExit(int opcode) {
                                    if (opcode != ATHROW) close(false);
                                }
                                @Override public void visitMaxs(int maxStack, int maxLocals) {
                                    visitLabel(end); visitTryCatchBlock(begin, end, handler, "java/lang/Throwable");
                                    visitLabel(handler);
                                    int error = newLocal(Type.getType(Throwable.class)); storeLocal(error);
                                    close(true); loadLocal(error); mv.visitInsn(ATHROW);
                                    super.visitMaxs(maxStack, maxLocals);
                                }
                            };
                        }
                    }, ClassReader.EXPAND_FRAMES);
                    System.out.println("RS_PROFILE_CLASS " + name);
                    return writer.toByteArray();
                } catch (Throwable failure) {
                    System.out.println("RS_PROFILE_TRANSFORM_FAILED " + name + " " + failure.getClass().getSimpleName());
                    return null;
                }
            }
        });
    }

    private record Hierarchy(String parent, String[] interfaces, int access) { }
    private static Hierarchy metadata(String type, ClassLoader loader, Map<String, Hierarchy> cache) {
        return cache.computeIfAbsent(type, key -> {
            try (InputStream stream = loader.getResourceAsStream(key + ".class")) {
                if (stream == null) throw new IllegalStateException("missing class resource");
                ClassReader reader = new ClassReader(stream);
                return new Hierarchy(reader.getSuperName(), reader.getInterfaces(), reader.getAccess());
            } catch (Exception error) { throw new IllegalStateException(error); }
        });
    }
    private static boolean assignable(String target, String type, ClassLoader loader, Map<String, Hierarchy> cache) {
        if (target.equals("java/lang/Object") || target.equals(type)) return true;
        Hierarchy meta = metadata(type, loader, cache);
        if (meta.parent != null && assignable(target, meta.parent, loader, cache)) return true;
        for (String contract : meta.interfaces) if (assignable(target, contract, loader, cache)) return true;
        return false;
    }

    private static boolean selectedClass(String name) {
        return name.startsWith("com/sinrotic/rs/agent/service/impl/")
                || name.startsWith("com/sinrotic/rs/recommend/service/impl/")
                || name.startsWith("com/sinrotic/rs/model/service/impl/")
                || name.equals("com/sinrotic/rs/user/service/UserSessionService")
                || name.equals("com/sinrotic/rs/recommend/controller/agent/AgentRecommendController")
                || name.equals("com/zaxxer/hikari/HikariDataSource")
                || name.equals("com/mysql/cj/jdbc/ConnectionImpl")
                || name.equals("com/mysql/cj/jdbc/ClientPreparedStatement")
                || name.equals("com/mysql/cj/jdbc/StatementImpl")
                || name.equals("com/mysql/cj/jdbc/ServerPreparedStatement")
                || name.equals("org/springframework/web/client/DefaultRestClient$DefaultRequestBodyUriSpec");
    }

    private static boolean selectedMethod(String name, String method) {
        if (name.equals("com/zaxxer/hikari/HikariDataSource")) return method.equals("getConnection");
        if (name.equals("com/mysql/cj/jdbc/ConnectionImpl"))
            return Set.of("commit", "rollback", "setAutoCommit").contains(method);
        if (name.startsWith("com/mysql/cj/jdbc/"))
            return Set.of("executeInternal", "executeUpdateInternal", "executeQuery", "execute", "executeBatchInternal").contains(method);
        if (name.startsWith("org/springframework/web/client/")) return method.equals("exchangeInternal");
        return !method.equals("setObservation");
    }

    private static boolean root(String name, String method) {
        return name.equals("com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService")
                && Set.of("chat", "streamChat").contains(method)
                || name.equals("com/sinrotic/rs/recommend/controller/agent/AgentRecommendController")
                || name.equals("com/sinrotic/rs/user/service/UserSessionService") && Set.of("admit", "get").contains(method)
                || name.equals("com/sinrotic/rs/model/service/impl/HttpModelGatewayService");
    }

    public static Object enter(String label, boolean root) {
        Trace trace = CURRENT.get();
        if (trace == null) {
            if (!root) return null;
            trace = new Trace(); CURRENT.set(trace);
        }
        Node node = new Node(label, trace.nodes.size(), trace.stack.isEmpty() ? -1 : trace.stack.peek().index);
        trace.nodes.add(node); trace.stack.push(node); return node;
    }

    public static void leave(Object token, boolean failed) {
        if (token == null) return;
        Trace trace = CURRENT.get(); Node node = (Node) token;
        if (trace == null || trace.stack.peek() != node) {
            CURRENT.remove(); System.out.println("RS_PROFILE_STACK_ERROR"); return;
        }
        node.duration = System.nanoTime() - node.start; node.failed = failed; trace.stack.pop();
        if (!trace.stack.isEmpty()) { trace.stack.peek().children += node.duration; return; }
        CURRENT.remove();
        StringBuilder out = new StringBuilder("RS_PROFILE {\"id\":").append(trace.id)
                .append(",\"epoch_ms\":").append(trace.epoch)
                .append(",\"thread\":").append(Thread.currentThread().threadId()).append(",\"nodes\":[");
        for (int i = 0; i < trace.nodes.size(); i++) {
            Node n = trace.nodes.get(i); if (i > 0) out.append(',');
            out.append("{\"method\":\"").append(n.label).append("\",\"parent\":").append(n.parent)
                    .append(",\"offset_ns\":").append(n.start - trace.nodes.get(0).start)
                    .append(",\"duration_ns\":").append(n.duration)
                    .append(",\"exclusive_ns\":").append(n.duration - n.children)
                    .append(",\"failed\":").append(n.failed).append('}');
        }
        System.out.println(out.append("]}"));
    }

    private static final class Trace {
        final long id = IDS.incrementAndGet(), epoch = System.currentTimeMillis();
        final List<Node> nodes = new ArrayList<>(); final Deque<Node> stack = new ArrayDeque<>();
    }
    private static final class Node {
        final String label; final int index, parent; final long start = System.nanoTime();
        long duration, children; boolean failed;
        Node(String label, int index, int parent) { this.label = label; this.index = index; this.parent = parent; }
    }
}
