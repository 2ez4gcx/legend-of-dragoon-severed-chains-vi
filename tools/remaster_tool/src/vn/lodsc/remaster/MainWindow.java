package vn.lodsc.remaster;

import javax.imageio.ImageIO;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.ButtonGroup;
import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JComponent;
import javax.swing.JFileChooser;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JProgressBar;
import javax.swing.JRadioButton;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.JToggleButton;
import javax.swing.ScrollPaneConstants;
import javax.swing.Scrollable;
import javax.swing.SwingConstants;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.UIManager;
import javax.swing.WindowConstants;
import javax.swing.filechooser.FileNameExtensionFilter;
import javax.swing.plaf.FontUIResource;
import java.awt.BorderLayout;
import java.awt.CardLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Container;
import java.awt.Desktop;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.Insets;
import java.awt.Rectangle;
import java.awt.RenderingHints;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Giao diện Swing (tiếng Việt, Segoe UI) gồm 6 màn: Kiểm tra, Công cụ, Tuỳ chọn, Đang tạo, Xong, Quản lý.
 * Mọi việc dài (tải, cài, chạy worker, chép, xoá) chạy trên một luồng nền; giao diện chỉ cập nhật trên EDT.
 * KHÔNG có kết nối mạng nào trước khi người chơi đánh dấu ô đồng ý của đúng công cụ đó rồi bấm "Tải và cài".
 */
final class MainWindow {
    static final Color C_OK = new Color(0x2E7D32);
    static final Color C_WARN = new Color(0xB26A00);
    static final Color C_FAIL = new Color(0xC62828);
    static final Color C_MUTED = new Color(0x5F6368);
    static final Color C_ACCENT = new Color(0x1A5FB4);
    static final String[] STEPS = {"1. Kiểm tra", "2. Công cụ", "3. Tuỳ chọn", "4. Đang tạo", "5. Xong", "6. Quản lý"};
    static final String[] CARDS = {"check", "tools", "options", "run", "done", "manage"};

    private final Layout g;
    private final Pins pins;
    private final boolean headless;
    final JPanel root = new JPanel(new BorderLayout());
    private final CardLayout cards = new CardLayout();
    private final JPanel content = new JPanel(cards);
    private final JToggleButton[] nav = new JToggleButton[STEPS.length];
    private final ExecutorService bg = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "remaster-tool-bg");
        t.setDaemon(true);
        return t;
    });
    private final List<JComponent> busyDisabled = new ArrayList<>();
    private volatile boolean busy;
    private volatile Runner runner;
    private volatile Downloader downloader;
    /** Thẻ công cụ đang tải (nút "Dừng tải" chỉ hiện ở đúng thẻ này). */
    private volatile ToolCard downloadCard;
    private volatile boolean pauseRequested;
    /** Người chơi đã bấm Tạm dừng/Huỷ trong lần chạy này (kể cả lúc chưa có tiến trình worker). */
    private volatile boolean stopPending;
    private JFrame frame;

    // màn Kiểm tra
    private final JPanel checkList = new JPanel(new GridBagLayout());
    private final JButton checkNext = new JButton("Tiếp tục →");
    // màn Công cụ
    private ToolCard blenderCard;
    private ToolCard esrganCard;
    private boolean skipAi;
    // màn Tuỳ chọn
    private final JRadioButton scopeV1 = new JRadioButton();
    private final JRadioButton scopeOpt = new JRadioButton();
    private final JRadioButton qPc = new JRadioButton("Máy tính (PC) — chi tiết cao nhất (L2, texture 4x)");
    private final JRadioButton qMobile = new JRadioButton("Điện thoại Android — nhẹ (L1, texture 2x)");
    private final JRadioButton qBoth = new JRadioButton("Cả hai");
    private final JRadioButton tAi = new JRadioButton("AI — Real-ESRGAN vẽ lại texture sắc nét (đẹp nhất)");
    private final JRadioButton tPlain = new JRadioButton("Phóng to thường (không AI)");
    private final JRadioButton tRetail = new JRadioButton("Giữ texture gốc (chỉ làm mịn hình khối)");
    private final JTextArea estimate = para("");
    private final JTextArea optionsNote = para("");
    private final JButton startBtn = new JButton("Bắt đầu tạo");
    // màn Đang tạo
    private final JLabel runStage = new JLabel(" ");
    private final JLabel runItem = new JLabel(" ");
    private final JLabel runTime = new JLabel(" ");
    private final JProgressBar runBar = new JProgressBar(0, 1000);
    private final JTextArea runLog = new JTextArea();
    private final JButton pauseBtn = new JButton("Tạm dừng");
    private final JButton cancelBtn = new JButton("Huỷ");
    private final JButton resumeBtn = new JButton("Tiếp tục");
    private final JTextArea runNote = para(" ");
    private long runStart;
    private final Timer clock;
    // màn Xong
    private final JLabel doneTitle = new JLabel("Chưa chạy");
    private final JTextArea doneSummary = para(" ");
    private final JTextArea doneErrors = new JTextArea();
    private final JCheckBox doneEnable = new JCheckBox("Bật mô hình HD khi chơi");
    // màn Quản lý
    private final JTextArea manageStatus = para("");
    private final JCheckBox manageEnable = new JCheckBox("Bật mô hình HD khi chơi");
    private boolean updatingToggle;
    /** Tuỳ chọn của lần tạo gần nhất đã xong (màn Xong bật theo đúng texture của lần đó). */
    private volatile Runner.Options lastRun;

    MainWindow(Layout g, Pins pins, boolean headless) {
        this.g = g;
        this.pins = pins;
        this.headless = headless;
        this.clock = new Timer(1000, e -> tickClock());
        build();
    }

    // ------------------------------------------------------------------ khởi động

    static void installLookAndFeel() {
        try {
            UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        } catch (Exception | Error ignored) {
            // giữ giao diện mặc định
        }
        Enumeration<Object> keys = UIManager.getDefaults().keys();
        List<Object> fontKeys = new ArrayList<>();
        while (keys.hasMoreElements()) {
            Object k = keys.nextElement();
            if (UIManager.get(k) instanceof FontUIResource) {
                fontKeys.add(k);
            }
        }
        for (Object k : fontKeys) {
            Font f = UIManager.getFont(k);
            UIManager.put(k, new FontUIResource("Segoe UI", f.getStyle(), 13));
        }
    }

    static void open(Layout g, Path pinsOverride) {
        installLookAndFeel();
        Pins pins;
        try {
            pins = Pins.load(Pins.locate(g, pinsOverride));
        } catch (IOException e) {
            JOptionPane.showMessageDialog(null, "Không đọc được pins.json: " + Util.msg(e)
                    + "\nHãy giải nén lại gói Việt hoá.", "Tạo mô hình HD", JOptionPane.ERROR_MESSAGE);
            System.exit(1);
            return;
        }
        MainWindow w = new MainWindow(g, pins, false);
        JFrame f = new JFrame("Tạo mô hình HD — The Legend of Dragoon (Severed Chains, bản Việt hoá)");
        w.frame = f;
        f.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
        f.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosing(WindowEvent e) {
                w.close();
            }
        });
        f.setContentPane(w.root);
        f.setSize(980, 700);
        f.setMinimumSize(new Dimension(820, 560));
        f.setLocationRelativeTo(null);
        f.setVisible(true);
        w.runChecks();
    }

    private void close() {
        if (busy || runner != null || downloader != null) {
            int a = JOptionPane.showConfirmDialog(frame, "Đang tạo, đang tải hoặc đang cài. Dừng lại và thoát?\n"
                            + "Lần sau mở công cụ sẽ chạy tiếp từ chỗ dừng (bản cài dở sẽ được cài lại).", "Thoát",
                    JOptionPane.YES_NO_OPTION, JOptionPane.WARNING_MESSAGE);
            if (a != JOptionPane.YES_OPTION) {
                return;
            }
            Runner r = runner;
            if (r != null) {
                r.cancel();
            }
            Downloader d = downloader;
            if (d != null) {
                d.cancel();
            }
        }
        frame.dispose();
        System.exit(0);
    }

    // ------------------------------------------------------------------ dựng giao diện

    private void build() {
        JPanel header = new JPanel(new BorderLayout());
        header.setBorder(BorderFactory.createEmptyBorder(14, 18, 10, 18));
        JLabel title = new JLabel("Tạo mô hình HD");
        title.setFont(new Font("Segoe UI", Font.BOLD, 22));
        JLabel sub = new JLabel("The Legend of Dragoon — Severed Chains, bản Việt hoá · công cụ "
                + Tool.VERSION + " · thư mục game: " + g.game());
        sub.setForeground(C_MUTED);
        header.add(title, BorderLayout.NORTH);
        header.add(sub, BorderLayout.SOUTH);
        root.add(header, BorderLayout.NORTH);

        JPanel side = new JPanel();
        side.setLayout(new BoxLayout(side, BoxLayout.Y_AXIS));
        side.setBorder(BorderFactory.createEmptyBorder(8, 12, 8, 6));
        ButtonGroup bgroup = new ButtonGroup();
        for (int i = 0; i < STEPS.length; i++) {
            final int k = i;
            JToggleButton b = new JToggleButton(STEPS[i]);
            b.setHorizontalAlignment(SwingConstants.LEFT);
            b.setMaximumSize(new Dimension(170, 36));
            b.setPreferredSize(new Dimension(170, 36));
            b.setAlignmentX(Component.LEFT_ALIGNMENT);
            b.addActionListener(e -> show(k));
            bgroup.add(b);
            nav[i] = b;
            side.add(b);
            side.add(Box.createVerticalStrut(4));
        }
        side.add(Box.createVerticalGlue());
        root.add(side, BorderLayout.WEST);

        content.setBorder(BorderFactory.createEmptyBorder(4, 12, 12, 18));
        content.add(buildCheck(), CARDS[0]);
        content.add(buildTools(), CARDS[1]);
        content.add(buildOptions(), CARDS[2]);
        content.add(buildRun(), CARDS[3]);
        content.add(buildDone(), CARDS[4]);
        content.add(buildManage(), CARDS[5]);
        root.add(content, BorderLayout.CENTER);
        show(0);
    }

    void show(int i) {
        cards.show(content, CARDS[i]);
        nav[i].setSelected(true);
        for (int k = 0; k < nav.length; k++) {
            nav[k].setFont(nav[k].getFont().deriveFont(k == i ? Font.BOLD : Font.PLAIN));
        }
        if (i == 2) {
            updateOptions();
        } else if (i == 5) {
            updateManage();
        }
    }

    /** Đoạn chữ tự xuống dòng theo bề rộng thật của cột (JTextArea chỉ đọc, trông như nhãn). */
    static JTextArea para(String text) {
        JTextArea a = new JTextArea(text);
        a.setLineWrap(true);
        a.setWrapStyleWord(true);
        a.setEditable(false);
        a.setFocusable(false);
        a.setOpaque(false);
        a.setBorder(BorderFactory.createEmptyBorder(1, 0, 1, 0));
        a.setFont(UIManager.getFont("Label.font"));
        a.setForeground(UIManager.getColor("Label.foreground"));
        a.setAlignmentX(Component.LEFT_ALIGNMENT);
        return a;
    }

    private static void setPara(JTextArea a, String text) {
        a.setText(text);
    }

    private static JLabel heading(String s) {
        JLabel l = new JLabel(s);
        l.setFont(new Font("Segoe UI", Font.BOLD, 17));
        l.setAlignmentX(Component.LEFT_ALIGNMENT);
        l.setBorder(BorderFactory.createEmptyBorder(0, 0, 8, 0));
        return l;
    }

    private static JPanel column() {
        JPanel p = new JPanel();
        p.setLayout(new BoxLayout(p, BoxLayout.Y_AXIS));
        return p;
    }

    private static JPanel row(Component... cs) {
        JPanel p = new JPanel(new FlowLayout(FlowLayout.LEFT, 0, 0));
        p.setAlignmentX(Component.LEFT_ALIGNMENT);
        for (int i = 0; i < cs.length; i++) {
            if (i > 0) {
                p.add(Box.createHorizontalStrut(8));
            }
            p.add(cs[i]);
        }
        p.setMaximumSize(new Dimension(Integer.MAX_VALUE, p.getPreferredSize().height + 4));
        return p;
    }

    /** Cột cuộn dọc: nội dung luôn rộng đúng bằng khung nhìn (không cuộn ngang), cao đúng theo nội dung. */
    private static final class TrackWidth extends JPanel implements Scrollable {
        TrackWidth(JComponent c) {
            super(new BorderLayout());
            add(c, BorderLayout.NORTH);
        }

        @Override
        public Dimension getPreferredScrollableViewportSize() {
            return getPreferredSize();
        }

        @Override
        public int getScrollableUnitIncrement(Rectangle r, int o, int d) {
            return 16;
        }

        @Override
        public int getScrollableBlockIncrement(Rectangle r, int o, int d) {
            return Math.max(16, r.height - 32);
        }

        @Override
        public boolean getScrollableTracksViewportWidth() {
            return true;
        }

        @Override
        public boolean getScrollableTracksViewportHeight() {
            return false;
        }
    }

    private static JScrollPane scroll(JComponent c) {
        JScrollPane sp = new JScrollPane(new TrackWidth(c), ScrollPaneConstants.VERTICAL_SCROLLBAR_AS_NEEDED,
                ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER);
        sp.setBorder(BorderFactory.createEmptyBorder());
        sp.getVerticalScrollBar().setUnitIncrement(16);
        return sp;
    }

    private JComponent buildCheck() {
        JPanel p = column();
        p.add(heading("Kiểm tra máy và thư mục game"));
        p.add(para("Công cụ tạo mô hình nhân vật HD (hình khối mịn hơn, texture rõ hơn) từ dữ liệu đĩa gốc của bạn mà"
                + " Severed Chains đã giải nén. Mọi thứ được tạo ngay trên máy này, nằm trong thư mục game và chỉ dùng"
                + " cho máy của bạn — không chia sẻ. Gói Việt hoá chỉ chứa mã nguồn, không chứa dữ liệu nào của Sony."
                + " Tắt hoặc gỡ lúc nào cũng được; khi tắt, game giống hệt bản gốc."));
        p.add(Box.createVerticalStrut(12));
        checkList.setAlignmentX(Component.LEFT_ALIGNMENT);
        p.add(checkList);
        p.add(Box.createVerticalStrut(12));
        JButton again = new JButton("Kiểm tra lại");
        again.addActionListener(e -> runChecks());
        checkNext.addActionListener(e -> show(1));
        busyDisabled.add(again);
        p.add(row(again, checkNext));
        p.add(Box.createVerticalGlue());
        return scroll(p);
    }

    private JComponent buildTools() {
        JPanel p = column();
        p.add(heading("Công cụ cần tải — chỉ tải khi bạn đồng ý"));
        p.add(para("Blender dùng để làm mịn hình khối nhân vật. Real-ESRGAN dùng AI để vẽ lại texture sắc nét (cần card"
                + " đồ hoạ hỗ trợ Vulkan; không có thì công cụ tự phóng to thường). Cả hai được tải từ nguồn chính thức,"
                + " kiểm SHA-256 đúng bản ghim rồi cài vào remaster_tools\\ trong thư mục game. Gói Việt hoá không kèm sẵn"
                + " các công cụ này. Nếu tải không được, có thể tự tải file zip rồi bấm \"Chọn file zip đã tải\"."));
        p.add(Box.createVerticalStrut(10));
        blenderCard = new ToolCard(pins.blender());
        esrganCard = new ToolCard(pins.esrgan());
        p.add(blenderCard.panel);
        p.add(Box.createVerticalStrut(10));
        p.add(esrganCard.panel);
        p.add(Box.createVerticalStrut(10));
        JButton next = new JButton("Tiếp tục →");
        next.addActionListener(e -> show(2));
        p.add(row(next));
        p.add(Box.createVerticalGlue());
        return scroll(p);
    }

    private JComponent buildOptions() {
        JPanel p = column();
        p.add(heading("Tuỳ chọn"));
        int[] cnt = Prereq.catalogCounts(g);
        scopeV1.setText("Nhân vật chơi được, mọi dạng (" + cnt[0] + " mô hình) — khuyên dùng");
        scopeOpt.setText("Thêm mô hình tuỳ chọn: dạng trẻ em, mô hình ghép đôi, … (+" + cnt[1] + ")");
        group(scopeV1, scopeOpt);
        group(qPc, qMobile, qBoth);
        group(tAi, tPlain, tRetail);
        scopeV1.setSelected(true);
        qPc.setSelected(true);
        tAi.setSelected(true);
        p.add(section("Phạm vi", scopeV1, scopeOpt));
        p.add(section("Chất lượng", qPc, qMobile, qBoth));
        p.add(section("Texture", tAi, tPlain, tRetail));
        for (JRadioButton b : List.of(scopeV1, scopeOpt, qPc, qMobile, qBoth, tAi, tPlain, tRetail)) {
            b.addActionListener(e -> updateOptions());
        }
        p.add(Box.createVerticalStrut(8));
        estimate.setAlignmentX(Component.LEFT_ALIGNMENT);
        p.add(estimate);
        p.add(Box.createVerticalStrut(4));
        optionsNote.setAlignmentX(Component.LEFT_ALIGNMENT);
        optionsNote.setForeground(C_WARN);
        p.add(optionsNote);
        p.add(Box.createVerticalStrut(10));
        startBtn.setFont(startBtn.getFont().deriveFont(Font.BOLD));
        startBtn.addActionListener(e -> startRun(false));
        busyDisabled.add(startBtn);
        p.add(row(startBtn));
        p.add(Box.createVerticalGlue());
        return scroll(p);
    }

    private static void group(JRadioButton... bs) {
        ButtonGroup bgp = new ButtonGroup();
        for (JRadioButton b : bs) {
            bgp.add(b);
        }
    }

    private static JPanel section(String title, JComponent... items) {
        JPanel s = column();
        s.setAlignmentX(Component.LEFT_ALIGNMENT);
        s.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createTitledBorder(title),
                BorderFactory.createEmptyBorder(2, 6, 4, 6)));
        for (JComponent c : items) {
            c.setAlignmentX(Component.LEFT_ALIGNMENT);
            s.add(c);
        }
        s.setMaximumSize(new Dimension(Integer.MAX_VALUE, s.getPreferredSize().height));
        return s;
    }

    private JComponent buildRun() {
        JPanel p = new JPanel(new BorderLayout(0, 8));
        JPanel top = column();
        top.add(heading("Đang tạo mô hình HD"));
        runStage.setFont(runStage.getFont().deriveFont(Font.BOLD, 14f));
        for (JLabel l : List.of(runStage, runItem, runTime)) {
            l.setAlignmentX(Component.LEFT_ALIGNMENT);
            top.add(l);
        }
        runBar.setAlignmentX(Component.LEFT_ALIGNMENT);
        runBar.setStringPainted(true);
        runBar.setMaximumSize(new Dimension(Integer.MAX_VALUE, 22));
        top.add(Box.createVerticalStrut(6));
        top.add(runBar);
        top.add(Box.createVerticalStrut(4));
        runNote.setAlignmentX(Component.LEFT_ALIGNMENT);
        top.add(runNote);
        p.add(top, BorderLayout.NORTH);
        runLog.setEditable(false);
        runLog.setFont(new Font("Consolas", Font.PLAIN, 12));
        runLog.setLineWrap(true);
        JScrollPane sp = new JScrollPane(runLog);
        sp.setBorder(BorderFactory.createTitledBorder("Nhật ký"));
        p.add(sp, BorderLayout.CENTER);
        pauseBtn.addActionListener(e -> stopRun(true));
        cancelBtn.addActionListener(e -> stopRun(false));
        resumeBtn.addActionListener(e -> startRun(false));
        resumeBtn.setVisible(false);
        pauseBtn.setEnabled(false);
        cancelBtn.setEnabled(false);
        JButton logs = new JButton("Mở thư mục log");
        logs.addActionListener(e -> openFolder(g.logs()));
        p.add(row(pauseBtn, cancelBtn, resumeBtn, logs), BorderLayout.SOUTH);
        return p;
    }

    private JComponent buildDone() {
        JPanel p = column();
        doneTitle.setFont(new Font("Segoe UI", Font.BOLD, 17));
        doneTitle.setAlignmentX(Component.LEFT_ALIGNMENT);
        doneTitle.setBorder(BorderFactory.createEmptyBorder(0, 0, 8, 0));
        p.add(doneTitle);
        doneSummary.setAlignmentX(Component.LEFT_ALIGNMENT);
        p.add(doneSummary);
        p.add(Box.createVerticalStrut(8));
        doneErrors.setEditable(false);
        doneErrors.setRows(6);
        doneErrors.setFont(new Font("Consolas", Font.PLAIN, 12));
        JScrollPane sp = new JScrollPane(doneErrors);
        sp.setBorder(BorderFactory.createTitledBorder("Mô hình lỗi (giữ nguyên bản gốc trong game)"));
        sp.setAlignmentX(Component.LEFT_ALIGNMENT);
        sp.setMaximumSize(new Dimension(Integer.MAX_VALUE, 150));
        p.add(sp);
        p.add(Box.createVerticalStrut(10));
        doneEnable.setAlignmentX(Component.LEFT_ALIGNMENT);
        doneEnable.setFont(doneEnable.getFont().deriveFont(Font.BOLD, 14f));
        doneEnable.addActionListener(e -> setEnabled(doneEnable.isSelected(), true));
        p.add(doneEnable);
        p.add(para("Có hiệu lực từ lần mở game sau. Tắt thì game giống hệt bản gốc."));
        p.add(Box.createVerticalStrut(10));
        JButton open = new JButton("Mở thư mục");
        open.addActionListener(e -> openFolder(g.remaster()));
        JButton exp = new JButton("Xuất gói Android (.zip)");
        exp.addActionListener(e -> exportAndroid());
        busyDisabled.add(exp);
        p.add(row(open, exp));
        p.add(Box.createVerticalGlue());
        return scroll(p);
    }

    private JComponent buildManage() {
        JPanel p = column();
        p.add(heading("Quản lý"));
        manageStatus.setAlignmentX(Component.LEFT_ALIGNMENT);
        p.add(manageStatus);
        p.add(Box.createVerticalStrut(10));
        manageEnable.setAlignmentX(Component.LEFT_ALIGNMENT);
        manageEnable.setFont(manageEnable.getFont().deriveFont(Font.BOLD, 14f));
        manageEnable.addActionListener(e -> setEnabled(manageEnable.isSelected(), false));
        p.add(manageEnable);
        p.add(Box.createVerticalStrut(10));
        JButton rebuild = new JButton("Tạo lại từ đầu (sau khi cập nhật bản Việt hoá)");
        rebuild.addActionListener(e -> {
            if (confirm("Xoá bộ đệm và tạo lại toàn bộ mô hình với tuỳ chọn ở màn Tuỳ chọn?")) {
                startRun(true);
            }
        });
        JButton copy = new JButton("Chép từ thư mục game cũ…");
        copy.addActionListener(e -> copyFromOld());
        JButton exp = new JButton("Xuất gói Android (.zip)");
        exp.addActionListener(e -> exportAndroid());
        JButton logs = new JButton("Mở thư mục log");
        logs.addActionListener(e -> openFolder(g.logs()));
        JButton delModels = new JButton("Xoá mô hình đã tạo");
        delModels.addActionListener(e -> uninstall("models"));
        JButton delTools = new JButton("Xoá công cụ đã tải");
        delTools.addActionListener(e -> uninstall("tools"));
        JButton all = new JButton("Gỡ hết");
        all.setForeground(C_FAIL);
        all.addActionListener(e -> uninstall("all"));
        busyDisabled.addAll(List.of(rebuild, copy, exp, delModels, delTools, all));
        p.add(row(rebuild, copy));
        p.add(Box.createVerticalStrut(6));
        p.add(row(exp, logs));
        p.add(Box.createVerticalStrut(14));
        JLabel danger = new JLabel("Dọn dẹp");
        danger.setFont(danger.getFont().deriveFont(Font.BOLD));
        danger.setAlignmentX(Component.LEFT_ALIGNMENT);
        p.add(danger);
        p.add(Box.createVerticalStrut(4));
        p.add(row(delModels, delTools, all));
        p.add(Box.createVerticalStrut(4));
        p.add(para("Gỡ hết = xoá remaster\\, remaster_work\\, remaster_tools\\, remaster_export\\, remaster.properties"
                + " và thư mục chạy AI bên ngoài (nếu có). Sau đó thư mục game như chưa từng dùng công cụ."));
        p.add(Box.createVerticalGlue());
        return scroll(p);
    }

    // ------------------------------------------------------------------ thẻ công cụ

    private final class ToolCard {
        final Pins.Tool t;
        final JPanel panel = column();
        final JLabel status = new JLabel();
        final JCheckBox consent;
        final JButton download = new JButton("Tải và cài");
        final JButton pick = new JButton("Chọn file zip đã tải…");
        final JButton skip = new JButton("Bỏ qua AI");
        final JButton recheck = new JButton("Kiểm tra lại");
        final JProgressBar bar = new JProgressBar(0, 1000);
        final JLabel detail = new JLabel(" ");

        ToolCard(Pins.Tool t) {
            this.t = t;
            panel.setAlignmentX(Component.LEFT_ALIGNMENT);
            panel.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createTitledBorder(
                            BorderFactory.createLineBorder(new Color(0xC8CCD0)), t.name + " " + t.version),
                    BorderFactory.createEmptyBorder(4, 8, 6, 8)));
            status.setFont(status.getFont().deriveFont(Font.BOLD));
            status.setAlignmentX(Component.LEFT_ALIGNMENT);
            panel.add(status);
            String role = t.isBlender() ? "Bắt buộc — làm mịn hình khối (chạy ngầm, không mở cửa sổ)."
                    : "Không bắt buộc — vẽ lại texture bằng AI (cần Vulkan).";
            panel.add(para(role + "\nNguồn: " + t.url + "\nDung lượng tải: " + Util.size(t.size)
                    + " · sau khi cài: khoảng " + Util.size(t.installed_size) + " · Giấy phép: " + t.license
                    + "\nCài vào: " + g.toolDir(t)));
            consent = new JCheckBox("Tôi đồng ý tải " + t.name + " " + t.version + " (" + Util.size(t.size)
                    + ", giấy phép " + t.license + ") từ " + t.host_label + ".");
            consent.setAlignmentX(Component.LEFT_ALIGNMENT);
            consent.addActionListener(e -> refresh());
            panel.add(Box.createVerticalStrut(4));
            panel.add(consent);
            download.addActionListener(e -> {
                Downloader d = downloader;
                if (d != null && downloadCard == this) {
                    d.cancel();
                } else {
                    doDownload(this);
                }
            });
            pick.addActionListener(e -> doPick(this));
            recheck.addActionListener(e -> doRecheck(this));
            recheck.setVisible(false);
            busyDisabled.add(recheck);
            skip.addActionListener(e -> {
                skipAi = true;
                tPlain.setSelected(true);
                refresh();
                show(2);
            });
            busyDisabled.add(pick);
            busyDisabled.add(skip);
            panel.add(Box.createVerticalStrut(4));
            panel.add(t.isEsrgan() ? row(download, pick, recheck, skip) : row(download, pick, recheck));
            bar.setAlignmentX(Component.LEFT_ALIGNMENT);
            bar.setStringPainted(true);
            bar.setVisible(false);
            bar.setMaximumSize(new Dimension(Integer.MAX_VALUE, 20));
            panel.add(Box.createVerticalStrut(4));
            panel.add(bar);
            detail.setAlignmentX(Component.LEFT_ALIGNMENT);
            detail.setForeground(C_MUTED);
            panel.add(detail);
            panel.setMaximumSize(new Dimension(Integer.MAX_VALUE, panel.getPreferredSize().height + 40));
        }

        void refresh() {
            Installer.Status s = Installer.status(g, t);
            String text = s.detail();
            Color c = s.ok() ? C_OK : s.state() == Installer.State.MISSING ? C_MUTED : C_WARN;
            if (t.isEsrgan()) {
                if (s.ok()) {
                    Staging.Result st = Staging.load(g, pins);
                    if (st != null && !st.aiOk()) {
                        text += " — nhưng không chạy được (" + st.detail() + "); sẽ phóng to thường";
                        c = C_WARN;
                    } else if (st != null) {
                        text += " — AI chạy được";
                    }
                } else if (skipAi) {
                    text = "Đã bỏ qua — texture sẽ phóng to thường (không AI)";
                }
            }
            status.setText("Trạng thái: " + text);
            status.setForeground(c);
            boolean dl = downloader != null && busy && downloadCard == this;
            download.setText(dl ? "Dừng tải" : s.ok() ? "Cài lại" : "Tải và cài");
            download.setEnabled(dl || (!busy && consent.isSelected()));
            boolean rc = s.state() == Installer.State.UNVERIFIED || (t.isEsrgan() && s.ok());
            recheck.setVisible(rc);
            recheck.setText(t.isEsrgan() && s.ok() ? "Tự kiểm AI lại" : "Kiểm tra lại");
        }
    }

    // ------------------------------------------------------------------ hành động

    private interface Job {
        void run() throws Exception;
    }

    private void ui(Runnable r) {
        if (SwingUtilities.isEventDispatchThread()) {
            r.run();
        } else {
            SwingUtilities.invokeLater(r);
        }
    }

    private void setBusy(boolean b) {
        busy = b;
        ui(() -> {
            for (JComponent c : busyDisabled) {
                c.setEnabled(!b);
            }
            refreshCards();
        });
    }

    private void refreshCards() {
        if (blenderCard != null) {
            blenderCard.refresh();
            esrganCard.refresh();
        }
    }

    /** Tải không thành công sau khi đã thử lại: mời người chơi chọn zip tự tải. */
    private static final class OfferManualZip extends Exception {
        final transient ToolCard card;

        OfferManualZip(String msg, ToolCard card) {
            super(msg);
            this.card = card;
        }
    }

    /** Chạy job trên luồng nền; lỗi → hộp thoại; xong → làm mới trạng thái. */
    private void background(String what, Job job) {
        if (busy) {
            info("Đang bận việc khác, hãy chờ.");
            return;
        }
        setBusy(true);
        bg.submit(() -> {
            OfferManualZip offer = null;
            try {
                job.run();
            } catch (OfferManualZip e) {
                offer = e;
            } catch (Exception e) {
                ui(() -> error(what + ": " + Util.msg(e)));
            } finally {
                setBusy(false);
                final OfferManualZip o = offer;
                ui(() -> {
                    updateOptions();
                    updateManage();
                    if (o != null && confirm(o.getMessage())) {
                        doPick(o.card);
                    }
                });
            }
        });
    }

    private void info(String s) {
        if (!headless) {
            JOptionPane.showMessageDialog(frame, s, "Tạo mô hình HD", JOptionPane.INFORMATION_MESSAGE);
        }
    }

    private void error(String s) {
        if (!headless) {
            JOptionPane.showMessageDialog(frame, s, "Tạo mô hình HD", JOptionPane.ERROR_MESSAGE);
        }
    }

    private boolean confirm(String s) {
        return !headless && JOptionPane.showConfirmDialog(frame, s, "Xác nhận", JOptionPane.YES_NO_OPTION,
                JOptionPane.WARNING_MESSAGE) == JOptionPane.YES_OPTION;
    }

    private boolean gameRunningBlocks() {
        if (Prereq.gameRunning(g)) {
            error("Game đang chạy từ thư mục này — hãy tắt game trước.");
            return true;
        }
        return false;
    }

    void runChecks() {
        background("Kiểm tra", () -> {
            List<Prereq.Check> cs = Prereq.run(g, pins, options());
            ui(() -> showChecks(cs));
        });
    }

    private void showChecks(List<Prereq.Check> cs) {
        checkList.removeAll();
        GridBagConstraints c = new GridBagConstraints();
        c.anchor = GridBagConstraints.NORTHWEST;
        c.insets = new Insets(3, 0, 3, 10);
        int y = 0;
        for (Prereq.Check k : cs) {
            c.gridy = y++;
            c.gridx = 0;
            c.weightx = 0;
            JLabel badge = new JLabel(switch (k.level()) {
                case OK -> "ĐẠT";
                case WARN -> "CẢNH BÁO";
                case FAIL -> "LỖI";
            });
            badge.setFont(badge.getFont().deriveFont(Font.BOLD));
            badge.setForeground(k.level() == Prereq.Level.OK ? C_OK : k.level() == Prereq.Level.WARN ? C_WARN : C_FAIL);
            checkList.add(badge, c);
            c.gridx = 1;
            JLabel t = new JLabel(k.title());
            t.setFont(t.getFont().deriveFont(Font.BOLD));
            checkList.add(t, c);
            c.gridx = 2;
            c.weightx = 1;
            c.fill = GridBagConstraints.HORIZONTAL;
            checkList.add(para(k.detail()), c);
            c.fill = GridBagConstraints.NONE;
        }
        checkNext.setEnabled(Prereq.ok(cs));
        checkList.revalidate();
        checkList.repaint();
    }

    private Runner.Options options() {
        Runner.Texture t = tAi.isSelected() ? Runner.Texture.AI : tPlain.isSelected() ? Runner.Texture.PLAIN : Runner.Texture.RETAIL;
        return new Runner.Options(scopeOpt.isSelected() ? "v1+optional" : "v1",
                qMobile.isSelected() ? "mobile" : qBoth.isSelected() ? "both" : "pc", t);
    }

    private void updateOptions() {
        Runner.Options o = options();
        Prereq.Estimate e = Prereq.estimate(g, pins, o);
        setPara(estimate, "Ước tính: " + e.models() + " mô hình, khoảng " + e.minLow() + "–" + e.minHigh()
                + " phút (tuỳ máy). Cần khoảng " + Util.size(e.totalBytes()) + " trống: dữ liệu tạo ra ~"
                + Util.size(e.outBytes()) + ", bộ đệm ~" + Util.size(e.workBytes())
                + (e.toolBytes() > 0 ? ", công cụ chưa cài ~" + Util.size(e.toolBytes()) : "") + ".");
        List<String> notes = new ArrayList<>();
        if (!Installer.status(g, pins.blender()).ok()) {
            notes.add("Chưa cài Blender — hãy cài ở màn Công cụ.");
        }
        boolean esrganOk = Installer.status(g, pins.esrgan()).ok();
        Staging.Result st = esrganOk ? Staging.load(g, pins) : null;
        if (o.texture() == Runner.Texture.AI && (!esrganOk || st == null || !st.aiOk())) {
            notes.add(esrganOk ? "Real-ESRGAN không chạy được trên máy này — texture sẽ được phóng to thường."
                    : "Chưa cài Real-ESRGAN — cài ở màn Công cụ, hoặc chọn \"Phóng to thường\".");
        }
        setPara(optionsNote, String.join(" ", notes));
        startBtn.setEnabled(!busy && Installer.status(g, pins.blender()).ok());
    }

    private void doDownload(ToolCard card) {
        if (!card.consent.isSelected()) {
            error("Hãy đánh dấu ô đồng ý trước.");
            return;
        }
        if (gameRunningBlocks()) {
            return;
        }
        Pins.Tool t = card.t;
        // đồng ý được đọc trên EDT đúng lúc bấm nút; Downloader.fetch từ chối (không mở mạng) nếu false
        final boolean consent = card.consent.isSelected();
        ui(() -> {
            card.bar.setVisible(true);
            card.bar.setValue(0);
        });
        background("Tải " + t.name, () -> {
            Downloader d = new Downloader(new Downloader.Listener() {
                @Override
                public void progress(long done, long total) {
                    ui(() -> {
                        card.bar.setValue((int) (total > 0 ? done * 1000 / total : 0));
                        card.bar.setString(Util.size(done) + " / " + Util.size(total));
                    });
                }

                @Override
                public void log(String msg) {
                    ui(() -> card.detail.setText(msg));
                }
            });
            downloadCard = card;
            downloader = d;
            ui(this::refreshCards);
            Path zip;
            try {
                zip = d.fetch(t, g.downloads(), consent);
            } catch (Downloader.DownloadException e) {
                downloader = null;
                if (e.kind == Downloader.DownloadException.Kind.CANCELED) {
                    ui(() -> card.detail.setText("Đã dừng tải. Bấm \"Tải và cài\" để tải tiếp."));
                    return;
                }
                ui(() -> card.detail.setText("Tải không thành công: " + Util.msg(e)));
                throw new OfferManualZip("Tải " + t.name + " không thành công:\n" + Util.msg(e)
                        + "\n\nBạn có thể tự tải file " + t.file + " (" + Util.size(t.size) + ") bằng trình duyệt từ\n"
                        + t.url + "\nrồi chọn file đó. Chọn file zip đã tải ngay bây giờ?", card);
            } finally {
                downloader = null;
                downloadCard = null;
            }
            install(card, zip, true);
        });
    }

    private void doRecheck(ToolCard card) {
        if (gameRunningBlocks()) {
            return;
        }
        background("Kiểm tra " + card.t.name, () -> {
            Installer.Status s = Installer.recheck(g, pins, card.t, new Installer.Listener() {
                @Override
                public void log(String msg) {
                    ui(() -> card.detail.setText(msg));
                }
            });
            ui(() -> card.detail.setText(s.ok() ? "Kiểm tra xong." : s.detail()));
        });
    }

    private void doPick(ToolCard card) {
        if (headless || gameRunningBlocks()) {
            return;
        }
        JFileChooser fc = new JFileChooser();
        fc.setDialogTitle("Chọn " + card.t.file);
        fc.setFileFilter(new FileNameExtensionFilter("Zip (" + card.t.file + ")", "zip"));
        if (fc.showOpenDialog(frame) != JFileChooser.APPROVE_OPTION) {
            return;
        }
        Path zip = fc.getSelectedFile().toPath();
        ui(() -> card.bar.setVisible(true));
        background("Cài " + card.t.name, () -> install(card, zip, false));
    }

    private void install(ToolCard card, Path zip, boolean owns) throws IOException {
        Installer.Status s = Installer.install(g, pins, card.t, zip, owns, new Installer.Listener() {
            @Override
            public void log(String msg) {
                ui(() -> card.detail.setText(msg));
            }

            @Override
            public void progress(long done, long total) {
                ui(() -> {
                    card.bar.setValue((int) (total > 0 ? done * 1000 / total : 0));
                    card.bar.setString("Giải nén " + (total > 0 ? done * 100 / total : 0) + "%");
                });
            }
        });
        if (card.t.isEsrgan()) {
            skipAi = false;
        }
        ui(() -> {
            card.bar.setVisible(false);
            card.detail.setText(s.ok() ? "Xong." : s.detail());
        });
        if (!s.ok()) {
            throw new IOException(s.detail());
        }
    }

    private void startRun(boolean rebuild) {
        if (busy) {
            info("Đang bận việc khác, hãy chờ.");
            return;
        }
        if (gameRunningBlocks()) {
            return;
        }
        if (!Installer.status(g, pins.blender()).ok()) {
            error("Chưa cài Blender — hãy cài ở màn Công cụ.");
            show(1);
            return;
        }
        Runner.Options o = options();
        List<Prereq.Check> cs = Prereq.run(g, pins, o);
        if (!Prereq.ok(cs)) {
            showChecks(cs);
            show(0);
            error("Chưa đủ điều kiện — xem màn Kiểm tra.");
            return;
        }
        pauseRequested = false;
        stopPending = false;
        runLog.setText("");
        runBar.setValue(0);
        runBar.setString("");
        runStage.setText("Đang khởi động…");
        runStage.setForeground(UIManager.getColor("Label.foreground"));
        runItem.setText(" ");
        setPara(runNote, " ");
        resumeBtn.setVisible(false);
        pauseBtn.setEnabled(true);
        cancelBtn.setEnabled(true);
        show(3);
        runStart = System.currentTimeMillis();
        clock.start();
        background("Tạo mô hình", () -> {
            try {
                // thư mục staging ASCII của Real-ESRGAN: kiểm lại đủ file + SHA-256 trước mỗi lần chạy, bị đổi thì
                // chép lại và tự kiểm lại (có thể mất vài chục giây nên chạy trên luồng nền); null = --no-ai
                Path esrganDir = null;
                if (o.texture() == Runner.Texture.AI) {
                    esrganDir = Staging.forRun(g, pins, this::appendLog);
                    if (esrganDir == null) {
                        ui(() -> setPara(runNote, "Real-ESRGAN chưa sẵn sàng hoặc không chạy được trên máy này"
                                + " — texture sẽ phóng to thường (không AI)."));
                    }
                }
                if (rebuild) {
                    Runner clean = new Runner(Runner.workerCommand(g, pins, "clean", List.of()), g.game(),
                            Runner.newLogFile(g, "clean"), runListener());
                    runner = clean;
                    if (stopPending) {
                        clean.cancel();
                    }
                    Runner.Result cr = clean.run();
                    if (cr.outcome() == Runner.Outcome.CANCELED) {
                        ui(() -> finishRun(cr, o));
                        return;
                    }
                    if (cr.outcome() != Runner.Outcome.DONE) {
                        throw new IOException("worker clean lỗi (mã " + cr.exit() + ")");
                    }
                }
                boolean resume = !rebuild && Runner.shouldResume(g);
                Runner r = new Runner(Runner.workerCommand(g, pins, "run", Runner.runArgs(g, pins, o, esrganDir, resume)),
                        g.game(), Runner.newLogFile(g, "run"), runListener());
                runner = r;
                if (stopPending) {
                    r.cancel();
                }
                appendLog(resume ? "Tiếp tục lần chạy trước (--resume)." : "Bắt đầu tạo.");
                Runner.Result res = r.run();
                ui(() -> finishRun(res, o));
            } catch (IOException | RuntimeException e) {
                ui(() -> {
                    runStage.setText("Không chạy được worker");
                    runStage.setForeground(C_FAIL);
                    setPara(runNote, Util.msg(e));
                    resumeBtn.setVisible(true);
                });
                throw e;
            } finally {
                runner = null;
                ui(() -> {
                    clock.stop();
                    pauseBtn.setEnabled(false);
                    cancelBtn.setEnabled(false);
                });
            }
        });
    }

    private Runner.Listener runListener() {
        return new Runner.Listener() {
            @Override
            public void progress(Runner.Progress p) {
                ui(() -> {
                    runStage.setText("Giai đoạn: " + stageName(p.stage()) + " — " + p.i() + "/" + p.n());
                    runItem.setText(p.label());
                    runBar.setValue(p.n() > 0 ? (int) (p.i() * 1000L / p.n()) : 0);
                    runBar.setString(p.n() > 0 ? (p.i() * 100 / p.n()) + "%" : "");
                });
            }

            @Override
            public void error(String key, String stage, String msg) {
                appendLog("LỖI " + stage + " " + key + ": " + msg);
            }

            @Override
            public void line(String s) {
                appendLog(s);
            }
        };
    }

    static String stageName(String s) {
        return switch (s) {
            case "S" -> "Quét dữ liệu (S)";
            case "E" -> "Xuất mô hình (E)";
            case "T" -> "Texture (T)";
            case "G" -> "Hình khối (G)";
            case "K" -> "Đóng gói (K)";
            case "V" -> "Kiểm tra (V)";
            case "C" -> "Ghi kết quả (C)";
            default -> s;
        };
    }

    private void appendLog(String s) {
        ui(() -> {
            runLog.append(s + "\n");
            if (runLog.getLineCount() > 3000) {
                try {
                    runLog.replaceRange("", 0, runLog.getLineEndOffset(500));
                } catch (javax.swing.text.BadLocationException ignored) {
                    // bỏ qua
                }
            }
            runLog.setCaretPosition(runLog.getDocument().getLength());
        });
    }

    private void tickClock() {
        long s = (System.currentTimeMillis() - runStart) / 1000;
        runTime.setText(String.format("Đã chạy %02d:%02d:%02d", s / 3600, (s / 60) % 60, s % 60));
    }

    private void stopRun(boolean pause) {
        if (!busy || stopPending) {
            return;
        }
        if (!pause && !confirm("Huỷ việc tạo? Phần đã xong được giữ; lần sau chạy tiếp từ chỗ dừng.")) {
            return;
        }
        pauseRequested = pause;
        stopPending = true;
        pauseBtn.setEnabled(false);
        cancelBtn.setEnabled(false);
        runStage.setText(pause ? "Đang tạm dừng…" : "Đang huỷ…");
        // chưa có tiến trình worker (đang chuẩn bị Real-ESRGAN): luồng nền thấy stopPending và dừng trước khi chạy
        Runner r = runner;
        if (r != null) {
            new Thread(r::cancel, "cancel").start();
        }
    }

    private void finishRun(Runner.Result res, Runner.Options o) {
        switch (res.outcome()) {
            case CANCELED -> {
                runStage.setText(pauseRequested ? "Đã tạm dừng" : "Đã huỷ");
                setPara(runNote, "Đã dừng worker và mọi tiến trình con. Bấm \"Tiếp tục\" để chạy tiếp từ chỗ dừng.");
                resumeBtn.setVisible(true);
                if (!pauseRequested) {
                    show(2);
                }
            }
            case FAILED -> {
                runStage.setText("Lỗi (mã " + res.exit() + ")");
                runStage.setForeground(C_FAIL);
                setPara(runNote, "Worker dừng vì lỗi. Xem nhật ký, rồi bấm \"Tiếp tục\" để thử lại. Log: " + res.log());
                resumeBtn.setVisible(true);
            }
            default -> {
                runStage.setForeground(null);
                lastRun = o;
                Runner.Done d = res.done();
                doneTitle.setText(res.outcome() == Runner.Outcome.DONE ? "Đã tạo xong" : "Đã tạo xong một phần");
                setPara(doneSummary, d == null ? "Worker kết thúc (mã " + res.exit() + ")."
                        : "Đã tạo " + d.ok() + " mô hình, lỗi " + d.failed() + ", bỏ qua " + d.skipped() + ", mất "
                        + String.format("%.1f", d.minutes()) + " phút. Mô hình lỗi giữ nguyên bản gốc trong game.");
                doneErrors.setText(res.errors().isEmpty() ? "(không có)" : String.join("\n", res.errors()));
                Toggle.State ts = Toggle.read(g);
                updatingToggle = true;
                doneEnable.setSelected(ts.enabled() && ts.hdTextures() == (o.texture() != Runner.Texture.RETAIL));
                updatingToggle = false;
                show(4);
            }
        }
    }

    /**
     * Bật/tắt mô hình HD (remaster.properties). Ở màn Xong: textures theo tuỳ chọn texture của lần tạo vừa xong. Ở màn
     * Quản lý: đã có remaster.properties thì giữ nguyên textures/log trong đó, chưa có thì theo màn Tuỳ chọn.
     */
    private void setEnabled(boolean on, boolean fromDone) {
        if (updatingToggle) {
            return;
        }
        try {
            if (on && !Files.isRegularFile(g.remaster().resolve("index.tsv"))) {
                error("Chưa có mô hình nào được tạo.");
                updateManage();
                doneEnable.setSelected(false);
                return;
            }
            if (fromDone && lastRun != null) {
                Toggle.set(g, on, lastRun.texture() != Runner.Texture.RETAIL);
            } else if (!fromDone && Files.isRegularFile(g.props())) {
                Toggle.setEnabled(g, on);
            } else {
                Toggle.set(g, on, options().texture() != Runner.Texture.RETAIL);
            }
        } catch (IOException e) {
            error("Không ghi được remaster.properties: " + Util.msg(e));
        }
        updatingToggle = true;
        doneEnable.setSelected(Toggle.read(g).enabled());
        manageEnable.setSelected(Toggle.read(g).enabled());
        updatingToggle = false;
        updateManage();
    }

    private void exportAndroid() {
        if (!Files.isRegularFile(g.remaster().resolve("index.tsv"))) {
            error("Chưa có mô hình nào để xuất.");
            return;
        }
        Path out = AndroidExport.defaultOut(g);
        background("Xuất gói Android", () -> {
            AndroidExport.Report rep = AndroidExport.export(g, pins, out, new Runner.Listener() {
            }, r -> runner = r);
            runner = null;
            ui(() -> {
                info("Đã xuất " + out.getFileName() + " (" + rep.models() + " mô hình, " + Util.size(rep.bytes()) + ").\n\n"
                        + "Chép file này vào điện thoại, mở app → \"Nhập mô hình HD (.zip)\" → bật \"Mô hình HD\".\n"
                        + "Gói được tạo từ đĩa gốc của bạn: chỉ dùng cho máy của bạn, KHÔNG chia sẻ.");
                openFolder(g.export());
            });
        });
    }

    private void copyFromOld() {
        if (headless || gameRunningBlocks()) {
            return;
        }
        JFileChooser fc = new JFileChooser();
        fc.setDialogTitle("Chọn thư mục game cũ (nơi có TAO_MO_HINH_HD.bat)");
        fc.setFileSelectionMode(JFileChooser.DIRECTORIES_ONLY);
        if (fc.showOpenDialog(frame) != JFileChooser.APPROVE_OPTION) {
            return;
        }
        Layout from = new Layout(fc.getSelectedFile().toPath());
        background("Chép từ thư mục cũ", () -> {
            StringBuilder log = new StringBuilder();
            OldFolderCopy.Result r = OldFolderCopy.copy(from, g, pins, s -> log.append(s).append('\n'), () -> false);
            ui(() -> {
                String msg = (r.models() ? "Đã chép mô hình. " : "") + (r.tools().isEmpty() ? "" : "Đã chép công cụ: "
                        + String.join(", ", r.tools()) + ". ") + (r.problems().isEmpty() ? "" : "\nVấn đề:\n- "
                        + String.join("\n- ", r.problems()));
                if (r.models() || !r.tools().isEmpty()) {
                    info(msg.strip());
                } else {
                    error("Không chép được gì." + msg);
                }
            });
        });
    }

    private void uninstall(String what) {
        if (gameRunningBlocks()) {
            return;
        }
        String q = switch (what) {
            case "models" -> "Xoá mọi mô hình đã tạo (remaster\\, remaster_work\\) và tắt Mô hình HD? Công cụ đã tải được giữ.";
            case "tools" -> "Xoá công cụ đã tải (Blender, Real-ESRGAN — khoảng " + Util.size(
                    pins.blender().installed_size + pins.esrgan().installed_size) + ")? Mô hình đã tạo được giữ.";
            default -> "Gỡ hết: xoá mô hình, công cụ, gói Android đã xuất và remaster.properties?";
        };
        if (!confirm(q)) {
            return;
        }
        background("Xoá", () -> {
            List<Path> done = switch (what) {
                case "models" -> Uninstaller.deleteModels(g);
                case "tools" -> Uninstaller.deleteTools(g, pins);
                default -> Uninstaller.removeAll(g, pins);
            };
            ui(() -> info(done.isEmpty() ? "Không có gì để xoá." : "Đã xoá:\n" + String.join("\n",
                    done.stream().map(Path::toString).toList())));
        });
    }

    private void updateManage() {
        Toggle.State s = Toggle.read(g);
        StringBuilder b = new StringBuilder();
        b.append("Mô hình HD khi chơi: ").append(s.enabled() ? "BẬT" : "TẮT")
                .append(s.enabled() ? (s.hdTextures() ? " (texture HD)" : " (texture gốc)") : "").append('\n');
        if (Files.isRegularFile(g.remaster().resolve("index.tsv"))) {
            try {
                Map<String, String> idx = RemasterData.parseIndex(Files.readAllBytes(g.remaster().resolve("index.tsv")));
                b.append("Đã tạo: ").append(idx.size()).append(" mô hình\n");
            } catch (IOException e) {
                b.append("Thư mục remaster\\ có vấn đề: ").append(Util.msg(e)).append('\n');
            }
        } else {
            b.append("Chưa tạo mô hình nào\n");
        }
        for (Pins.Tool t : pins.tools) {
            b.append(t.name).append(": ").append(Installer.status(g, t).detail()).append('\n');
        }
        Staging.Result st = Staging.load(g, pins);
        if (st != null) {
            b.append("Thư mục chạy AI: ").append(st.dir()).append(st.aiOk() ? " (tự kiểm đạt)" : " (" + st.detail() + ")");
        }
        setPara(manageStatus, b.toString().strip());
        updatingToggle = true;
        manageEnable.setSelected(s.enabled());
        updatingToggle = false;
        refreshCards();
    }

    private void openFolder(Path p) {
        if (headless) {
            return;
        }
        try {
            if (!Files.isDirectory(p)) {
                error("Chưa có thư mục " + p);
                return;
            }
            Desktop.getDesktop().open(p.toFile());
        } catch (IOException | RuntimeException e) {
            error("Không mở được " + p + ": " + Util.msg(e));
        }
    }

    // ------------------------------------------------------------------ xem trước không cửa sổ

    private static void invalidateTree(Component c) {
        c.invalidate();
        if (c instanceof Container ct) {
            for (Component k : ct.getComponents()) {
                invalidateTree(k);
            }
        }
    }

    private static void layoutTree(Component c) {
        if (c instanceof Container ct) {
            ct.doLayout();
            for (Component k : ct.getComponents()) {
                layoutTree(k);
            }
        }
    }

    /** --render-screens &lt;dir&gt;: vẽ 6 màn ra PNG (trạng thái mẫu cho màn Đang tạo/Xong). Không mở mạng. */
    static int renderScreens(List<String> args) {
        System.setProperty("java.awt.headless", "true");
        Path out = Tool.argPath(args, "--render-screens");
        Layout g = new Layout(Tool.gameFromArgs(args));
        try {
            Pins pins = Pins.load(Pins.locate(g, Tool.argPath(args, "--pins")));
            installLookAndFeel();
            Files.createDirectories(out);
            final int[] rc = {0};
            SwingUtilities.invokeAndWait(() -> {
                try {
                    MainWindow w = new MainWindow(g, pins, true);
                    w.blenderCard.refresh();
                    w.esrganCard.refresh();
                    w.showChecks(Prereq.run(g, pins, w.options()));
                    w.runStage.setText("Giai đoạn: " + stageName("G") + " — 12/96");
                    w.runItem.setText("(mẫu) dart — chiến đấu");
                    w.runBar.setValue(125);
                    w.runBar.setString("12%");
                    w.runTime.setText("Đã chạy 00:03:12");
                    w.pauseBtn.setEnabled(true);
                    w.cancelBtn.setEnabled(true);
                    w.runLog.setText("(mẫu) Bắt đầu tạo.\n(mẫu) [S] quét 6722 file trường …\n");
                    w.doneTitle.setText("Đã tạo xong");
                    setPara(w.doneSummary, "(mẫu) Đã tạo 105 mô hình, lỗi 2, bỏ qua 0, mất 18,4 phút.");
                    w.doneErrors.setText("(mẫu) G 0123…: quá giờ\n(mẫu) G 4567…: lỗi Blender");
                    for (int i = 0; i < STEPS.length; i++) {
                        w.show(i);
                        w.root.setSize(980, 700);
                        for (int pass = 0; pass < 4; pass++) {
                            w.root.invalidate();
                            invalidateTree(w.root);
                            layoutTree(w.root);
                        }
                        BufferedImage img = new BufferedImage(980, 700, BufferedImage.TYPE_INT_RGB);
                        Graphics2D g2 = img.createGraphics();
                        g2.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_LCD_HRGB);
                        g2.setColor(w.root.getBackground());
                        g2.fillRect(0, 0, 980, 700);
                        w.root.printAll(g2);
                        g2.dispose();
                        File f = out.resolve(String.format("man_%d_%s.png", i + 1, CARDS[i])).toFile();
                        ImageIO.write(img, "png", f);
                        System.out.println("Đã vẽ " + f);
                    }
                } catch (IOException e) {
                    System.out.println("LỖI: " + Util.msg(e));
                    rc[0] = 1;
                }
            });
            return rc[0];
        } catch (Exception e) {
            System.out.println("LỖI: " + Util.msg(e));
            return 1;
        }
    }
}
