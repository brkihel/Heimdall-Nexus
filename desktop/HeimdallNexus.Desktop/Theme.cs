using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Reflection;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>The Heimdall look: dark background, gold accents, like the panel and the site.</summary>
    static class Theme
    {
        public static readonly Color Background = ColorTranslator.FromHtml("#0d151d");
        public static readonly Color Card = ColorTranslator.FromHtml("#16232e");
        public static readonly Color Line = ColorTranslator.FromHtml("#33475a");
        public static readonly Color Gold = ColorTranslator.FromHtml("#c8a45c");
        public static readonly Color GoldLight = ColorTranslator.FromHtml("#eeddb0");
        public static readonly Color Text = ColorTranslator.FromHtml("#f5f0e8");
        public static readonly Color Muted = ColorTranslator.FromHtml("#9cacb9");
        public static readonly Color Good = ColorTranslator.FromHtml("#5aa36f");
        public static readonly Color Bad = ColorTranslator.FromHtml("#b0574a");
        public static readonly Color Busy = ColorTranslator.FromHtml("#d0a54e");

        public static Font Title => new Font("Georgia", 18f, FontStyle.Bold);
        public static Font Heading => new Font("Segoe UI Semibold", 11.5f);
        public static Font Body => new Font("Segoe UI", 10f);
        public static Font Small => new Font("Segoe UI", 9f);

        public static Icon AppIcon()
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("heimdall.ico"))
                return stream == null ? SystemIcons.Application : new Icon(stream);
        }

        public static void Style(Form form, string title)
        {
            form.Text = "Heimdall Nexus";
            form.Icon = AppIcon();
            form.BackColor = Background;
            form.ForeColor = Text;
            form.Font = Body;
            form.FormBorderStyle = FormBorderStyle.FixedSingle;
            form.MaximizeBox = false;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.AutoScaleMode = AutoScaleMode.Dpi;
        }

        public static Label Label(string text, Font font = null, Color? color = null, int width = 560)
        {
            return new Label
            {
                Text = text, Font = font ?? Body, ForeColor = color ?? Text, AutoSize = true,
                MaximumSize = new Size(width, 0), BackColor = Color.Transparent, Margin = new Padding(0, 0, 0, 8),
            };
        }

        public static Button Button(string text, bool primary = true)
        {
            var button = new Button
            {
                Text = text, FlatStyle = FlatStyle.Flat, AutoSize = true, Padding = new Padding(14, 6, 14, 6),
                Font = new Font("Segoe UI Semibold", 10f), Cursor = Cursors.Hand,
                BackColor = primary ? Gold : Card, ForeColor = primary ? Background : Text,
                Margin = new Padding(0, 4, 10, 4), UseVisualStyleBackColor = false,
            };
            button.FlatAppearance.BorderColor = primary ? Gold : Line;
            button.FlatAppearance.MouseOverBackColor = primary ? GoldLight : Line;
            return button;
        }

        /// <summary>A header with the Heimdall icon and a title.</summary>
        public static Control Header(string title)
        {
            var panel = new FlowLayoutPanel
            {
                AutoSize = true, FlowDirection = FlowDirection.LeftToRight, WrapContents = false,
                Margin = new Padding(0, 0, 0, 14), BackColor = Color.Transparent,
            };
            var picture = new PictureBox
            {
                Image = new Icon(AppIcon(), 48, 48).ToBitmap(), SizeMode = PictureBoxSizeMode.Zoom,
                Size = new Size(44, 44), Margin = new Padding(0, 0, 12, 0),
            };
            var label = Label(title, Title, GoldLight);
            label.Margin = new Padding(0, 6, 0, 0);
            panel.Controls.Add(picture);
            panel.Controls.Add(label);
            return panel;
        }
    }

    /// <summary>A card: a slightly lighter panel with a thin border.</summary>
    class Card : FlowLayoutPanel
    {
        public Card()
        {
            FlowDirection = FlowDirection.TopDown;
            WrapContents = false;
            AutoSize = true;
            BackColor = Theme.Card;
            Padding = new Padding(16, 12, 16, 12);
            Margin = new Padding(0, 0, 0, 12);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (var pen = new Pen(Theme.Line))
                e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }
    }

    /// <summary>An on/off switch drawn like the ones in the panel and the setup wizard.</summary>
    class Switch : CheckBox
    {
        public Switch()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Size = new Size(46, 24);
            Cursor = Cursors.Hand;
            Margin = new Padding(0, 2, 12, 0);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Parent?.BackColor ?? Theme.Card);
            var track = new Rectangle(1, 1, Width - 3, Height - 3);
            using (var path = Rounded(track, track.Height / 2))
            using (var fill = new SolidBrush(Checked ? Color.FromArgb(70, Theme.Gold) : Theme.Background))
            using (var pen = new Pen(Checked ? Theme.Gold : Theme.Line))
            {
                g.FillPath(fill, path);
                g.DrawPath(pen, path);
            }
            int knob = track.Height - 6;
            int x = Checked ? track.Right - knob - 3 : track.Left + 3;
            using (var brush = new SolidBrush(Enabled ? (Checked ? Theme.GoldLight : Theme.Muted) : Theme.Line))
                g.FillEllipse(brush, x, track.Top + 3, knob, knob);
            if (Focused)
                ControlPaint.DrawFocusRectangle(g, ClientRectangle);
        }

        static GraphicsPath Rounded(Rectangle r, int radius)
        {
            var path = new GraphicsPath();
            int d = radius * 2;
            path.AddArc(r.X, r.Y, d, d, 180, 90);
            path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    /// <summary>A small colored dot for on, off and busy.</summary>
    class Dot : Control
    {
        Color color = Theme.Muted;

        public Dot()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.SupportsTransparentBackColor, true);
            Size = new Size(14, 14);
            Margin = new Padding(0, 5, 8, 0);
            BackColor = Color.Transparent;
        }

        public Color Color { get => color; set { color = value; Invalidate(); } }

        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var brush = new SolidBrush(color))
                e.Graphics.FillEllipse(brush, 1, 1, Width - 3, Height - 3);
        }
    }
}
